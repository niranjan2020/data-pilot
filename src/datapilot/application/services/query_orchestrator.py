"""Application service coordinating semantic matching, SQL generation, safety and execution."""

from __future__ import annotations

from typing import Any, Dict, Optional

from datapilot.application.services.entity_resolver import DeterministicEntityResolver
from datapilot.core.exceptions import SQLValidationError
from datapilot.core.logging import get_logger
from datapilot.domain.interfaces.database import DatabaseProvider
from datapilot.domain.interfaces.entity_resolver import EntityResolver
from datapilot.domain.interfaces.query_policy import QueryPolicyEnforcer
from datapilot.domain.interfaces.semantic import SemanticCatalogProvider
from datapilot.domain.interfaces.semantic_retriever import SemanticRetriever
from datapilot.domain.interfaces.sql_generator import SQLGenerator
from datapilot.domain.interfaces.sql_validator import SQLValidator
from datapilot.domain.models import SchemaMetadata
from datapilot.domain.policies import QueryExecutionPolicy
from datapilot.domain.query import QueryRequest, QueryResponse
from datapilot.domain.semantic import QueryIntent, SemanticCatalog
from datapilot.infrastructure.sql.query_policy import SQLQueryPolicyEnforcer


logger = get_logger("datapilot.query")

class QueryOrchestrator:
    """Execute the core query workflow independently of any LLM vendor."""

    def __init__(
        self,
        database_provider: DatabaseProvider,
        sql_validator: SQLValidator,
        sql_generator: SQLGenerator,
        semantic_catalog_provider: SemanticCatalogProvider,
        *,
        entity_resolver: Optional[EntityResolver] = None,
        query_policy_enforcer: Optional[QueryPolicyEnforcer] = None,
        query_policy: Optional[QueryExecutionPolicy] = None,
        query_timeout_seconds: Optional[float] = None,
        semantic_retriever: Optional[SemanticRetriever] = None,
        semantic_retrieval_limit: int = 8,
    ) -> None:
        self._database = database_provider
        self._validator = sql_validator
        self._sql_generator = sql_generator
        self._semantic_catalog_provider = semantic_catalog_provider
        self._semantic_retriever = semantic_retriever
        self._semantic_retrieval_limit = semantic_retrieval_limit
        self._entity_resolver = entity_resolver or DeterministicEntityResolver()
        self._query_policy = query_policy or QueryExecutionPolicy()
        if query_timeout_seconds is not None:
            self._query_policy = self._query_policy.model_copy(
                update={"timeout_seconds": query_timeout_seconds}
            )
        self._query_policy_enforcer = query_policy_enforcer or SQLQueryPolicyEnforcer()

    async def query(
        self,
        request: QueryRequest,
        *,
        schema: Optional[SchemaMetadata] = None,
        catalog: Optional[SemanticCatalog] = None,
    ) -> QueryResponse:
        """Resolve, generate, validate and execute one natural-language query."""
        retrieved_context: list[dict[str, Any]] = []
        if self._semantic_retriever is not None and request.source_name:
            retrieved_context = await self._semantic_retriever.search(
                request.source_name, request.question, self._semantic_retrieval_limit
            )

        logger.info(
            "query question=%r source=%r retrieved=%s",
            request.question, request.source_name,
            [(x.get("kind"), x.get("name"), x.get("score")) for x in retrieved_context],
        )
        schema = schema or await self._load_relevant_schema(retrieved_context)
        logger.info(
            "query physical_schema tables=%s",
            [f"{t.schema_name}.{t.name}" for t in schema.tables],
        )
        catalog = catalog or await self._semantic_catalog_provider.get_catalog()

        intent = self._entity_resolver.resolve(request.question, catalog, schema)
        if intent.ambiguities:
            return QueryResponse(
                question=request.question,
                status="ambiguous",
                confidence=intent.confidence,
                semantic_ambiguities=intent.ambiguities,
                resolved_intent=intent,
                message="The question matches more than one semantic entity. Refine the entity name or add an explicit attribute.",
            )

        parameters = self._merge_resolved_parameters(request.parameters, intent)
        generated = await self._sql_generator.generate(
            question=request.question,
            schema=schema,
            context={
                "retrieved_semantic_context": retrieved_context,
                "semantic_catalog": catalog.model_dump(mode="json"),
                "query_intent": intent.model_dump(mode="json"),
                "parameters": parameters,
            },
            dialect=self._database.dialect,
        )
        logger.info("query generated_sql=%s", generated)
        return await self._validate_and_execute(
            question=request.question,
            sql=generated,
            source="generator",
            confidence=intent.confidence,
            resolved_intent=intent,
            retrieved_context=retrieved_context,
        )

    async def _validate_and_execute(
        self,
        *,
        question: str,
        sql: str,
        source: str,
        confidence: float,
        resolved_intent: Optional[QueryIntent] = None,
        retrieved_context: Optional[list[dict[str, Any]]] = None,
    ) -> QueryResponse:
        validation = await self._validator.validate(
            sql,
            dialect=self._database.dialect,
            enforce_read_only=True,
        )
        if not validation.is_valid:
            raise SQLValidationError(
                "Generated SQL failed safety validation",
                details={"errors": validation.errors},
            )

        executable_sql = validation.sanitized_sql or sql
        logger.info(
            "query validated_sql=%s affected_tables=%s warnings=%s",
            executable_sql, validation.affected_tables, validation.warnings,
        )
        policy_result = self._query_policy_enforcer.enforce(
            executable_sql,
            self._database.dialect,
            self._query_policy,
        )
        if not policy_result.is_allowed:
            raise SQLValidationError(
                "SQL query failed execution policy",
                details={"errors": policy_result.errors},
            )

        logger.info(
            "query executable_sql=%s policy_warnings=%s",
            policy_result.sql, policy_result.warnings,
        )
        result = await self._database.execute_query(
            policy_result.sql,
            timeout_seconds=self._query_policy.timeout_seconds,
        )
        logger.info(
            "query completed rows=%s execution_time_ms=%.2f",
            result.row_count, result.execution_time_ms,
        )
        if result.row_count > self._query_policy.max_result_rows:
            raise SQLValidationError(
                "Query result exceeded the configured maximum row count",
                details={
                    "row_count": result.row_count,
                    "max_result_rows": self._query_policy.max_result_rows,
                },
            )

        return QueryResponse(
            question=question,
            status="completed",
            source=source,
            sql=policy_result.sql,
            result=result,
            confidence=confidence,
            resolved_intent=resolved_intent,
            retrieved_context=retrieved_context or [],
            validation_warnings=[*validation.warnings, *policy_result.warnings],
        )

    async def _load_relevant_schema(
        self, retrieved_context: list[dict[str, Any]]
    ) -> SchemaMetadata:
        """Introspect only physical schemas surfaced by governed semantic retrieval."""
        schema_names = sorted({
            item.get("metadata", {}).get("schema_name")
            for item in retrieved_context
            if item.get("kind") == "entity" and item.get("metadata", {}).get("schema_name")
        })
        if not schema_names:
            return await self._database.introspect_schema()

        discovered = [await self._database.introspect_schema(name) for name in schema_names]
        tables = [table for item in discovered for table in item.tables]
        return SchemaMetadata(
            schema_name=None,
            tables=tables,
            dialect=self._database.dialect,
        )

    @staticmethod
    def _merge_resolved_parameters(
        parameters: Dict[str, Any],
        intent: QueryIntent,
    ) -> Dict[str, Any]:
        """Fill missing parameters from deterministic semantic filters."""
        merged = dict(parameters)
        for item in intent.filters:
            for key in (item.attribute, item.column_name):
                if key not in merged:
                    merged[key] = item.value
        return merged

