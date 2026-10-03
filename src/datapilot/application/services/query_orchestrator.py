"""Application service coordinating semantic matching, SQL generation, safety and execution."""

from __future__ import annotations

from typing import Any, Dict, Optional

from datapilot.application.services.entity_resolver import DeterministicEntityResolver
from datapilot.application.services.context_budget import ContextBudgeter
from datapilot.application.services.semantic_context import SemanticContextAssembler
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
from datapilot.domain.query import QueryRequest, QueryResponse, QueryTrace
from datapilot.domain.semantic import QueryIntent, SemanticCatalog
from datapilot.infrastructure.sql.query_policy import SQLQueryPolicyEnforcer
from datapilot.infrastructure.sql.identifier_binding import bind_physical_identifiers


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
        semantic_context_assembler: Optional[SemanticContextAssembler] = None,
        context_budget_chars: int = 24000,
    ) -> None:
        self._database = database_provider
        self._validator = sql_validator
        self._sql_generator = sql_generator
        self._semantic_catalog_provider = semantic_catalog_provider
        self._semantic_retriever = semantic_retriever
        self._semantic_retrieval_limit = semantic_retrieval_limit
        self._semantic_context_assembler = semantic_context_assembler
        self._context_budgeter = ContextBudgeter(context_budget_chars)
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
            # Stage 1 discovers the relevant physical/business neighborhood rather
            # than allowing rules/metrics to crowd datasets out of a flat top-k.
            search_kinds = getattr(self._semantic_retriever, "search_kinds", None)
            if search_kinds is not None:
                seed_limit = max(4, min(self._semantic_retrieval_limit, 6))
                structural_seeds = await search_kinds(
                    request.source_name, request.question,
                    ["dataset", "entity"], seed_limit,
                )
                # Stage 2 retrieves semantic intent objects independently. They do
                # not select physical datasets; the authoritative catalog later
                # constrains them to the Stage-1 dataset/entity neighborhood.
                intent_seeds = await search_kinds(
                    request.source_name, request.question,
                    ["metric", "business_rule"], seed_limit,
                )
                retrieved_context = [*structural_seeds, *intent_seeds]
            else:
                retrieved_context = await self._semantic_retriever.search(
                    request.source_name, request.question, self._semantic_retrieval_limit
                )

        logger.info(
            "query question=%r source=%r retrieval_stage=hierarchical_seeds retrieved=%s",
            request.question, request.source_name,
            [(x.get("kind"), x.get("name"), x.get("score")) for x in retrieved_context],
        )
        governed_context: dict[str, Any] = {}
        if self._semantic_context_assembler is not None and request.source_name:
            governed_context = await self._semantic_context_assembler.assemble(
                request.source_name, retrieved_context, request.question
            )
            logger.info(
                "query governed_context datasets=%s entities=%s relationships=%s metrics=%s rules=%s",
                [f"{x['schema_name']}.{x['table_name']}" for x in governed_context.get("datasets", [])],
                [x["name"] for x in governed_context.get("entities", [])],
                [x["name"] for x in governed_context.get("relationships", [])],
                [x["name"] for x in governed_context.get("metrics", [])],
                [x["name"] for x in governed_context.get("business_rules", [])],
            )
        schema = schema or await self._load_relevant_schema(
            retrieved_context, governed_context, request.question
        )
        logger.info(
            "query physical_schema tables=%s",
            [f"{t.schema_name}.{t.name}" for t in schema.tables],
        )
        trace = QueryTrace(
            retrieved_candidates=retrieved_context,
            governed_datasets=[
                f"{x['schema_name']}.{x['table_name']}"
                for x in governed_context.get("datasets", [])
            ],
            governed_entities=[x["name"] for x in governed_context.get("entities", [])],
            governed_relationships=[x["name"] for x in governed_context.get("relationships", [])],
            governed_metrics=[x["name"] for x in governed_context.get("metrics", [])],
            governed_business_rules=[x["name"] for x in governed_context.get("business_rules", [])],
            physical_tables=[f"{t.schema_name}.{t.name}" for t in schema.tables],
            physical_columns={
                f"{t.schema_name}.{t.name}": [column.name for column in t.columns]
                for t in schema.tables
            },
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
                trace=trace,
                message="The question matches more than one semantic entity. Refine the entity name or add an explicit attribute.",
            )

        parameters = self._merge_resolved_parameters(request.parameters, intent)
        generation_context = {
            "governed_semantic_context": governed_context,
            "retrieved_semantic_context": retrieved_context,
            "semantic_catalog": catalog.model_dump(mode="json"),
            "query_intent": intent.model_dump(mode="json"),
            "parameters": parameters,
        }
        generation_context, budget = self._context_budgeter.apply(generation_context)
        logger.info("query context_budget=%s", budget)
        trace.context_budget = budget
        generated = await self._sql_generator.generate(
            question=request.question,
            schema=schema,
            context=generation_context,
            dialect=self._database.dialect,
        )
        logger.info("query generated_sql=%s", generated)
        bound_sql = bind_physical_identifiers(generated, schema, self._database.dialect)
        logger.info("query catalog_bound_sql=%s", bound_sql)
        return await self._validate_and_execute(
            question=request.question,
            sql=bound_sql,
            source="generator",
            confidence=intent.confidence,
            resolved_intent=intent,
            retrieved_context=retrieved_context,
            trace=trace,
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
        trace: Optional[QueryTrace] = None,
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
        self,
        retrieved_context: list[dict[str, Any]],
        governed_context: Optional[dict[str, Any]] = None,
        question: str = "",
    ) -> SchemaMetadata:
        """Introspect physical schemas, then prune tables and governed columns."""
        governed_entities = (governed_context or {}).get("entities", [])
        governed_datasets = (governed_context or {}).get("datasets", [])
        physical_tables = {
            (d.get("schema_name"), d.get("table_name"))
            for d in governed_datasets
            if d.get("schema_name") and d.get("table_name")
        }
        physical_tables.update({
            (e.get("schema_name"), e.get("table_name"))
            for e in governed_entities
            if e.get("schema_name") and e.get("table_name")
        })
        if not physical_tables:
            physical_tables = {
                (item.get("metadata", {}).get("schema_name"), item.get("metadata", {}).get("table_name"))
                for item in retrieved_context
                if item.get("kind") == "entity"
                and item.get("metadata", {}).get("schema_name")
                and item.get("metadata", {}).get("table_name")
            }
        if not physical_tables:
            return await self._database.introspect_schema()

        schema_names = sorted({schema for schema, _ in physical_tables})
        discovered = [await self._database.introspect_schema(name) for name in schema_names]
        tables = [
            table
            for item in discovered
            for table in item.tables
            if (table.schema_name or item.schema_name, table.name) in physical_tables
        ]

        # Governed column pruning. Required join/key/display/metric columns are
        # always retained. Explicitly mentioned semantic attributes are retained.
        # If an entity has no configured attributes, keep its full physical table
        # as a safe compatibility fallback rather than guessing.
        entities = governed_entities
        relationships = (governed_context or {}).get("relationships", [])
        metrics = (governed_context or {}).get("metrics", [])
        normalized_question = " " + __import__("re").sub(
            r"[^a-z0-9]+", " ", question.lower()
        ).strip() + " "
        required: dict[tuple[str, str], set[str]] = {}

        def require(schema_name: str | None, table_name: str | None, column: str | None) -> None:
            if schema_name and table_name and column:
                required.setdefault((schema_name, table_name), set()).add(column.lower())

        entity_by_id = {e["id"]: e for e in entities}
        for entity in entities:
            key = (entity.get("schema_name"), entity.get("table_name"))
            require(*key, entity.get("key_column"))
            require(*key, entity.get("display_column"))
            attributes = entity.get("attributes") or []
            for attribute in attributes:
                terms = [
                    attribute.get("name") or "",
                    *(attribute.get("synonyms") or []),
                ]
                if any(
                    (term_norm := __import__("re").sub(
                        r"[^a-z0-9]+", " ", term.lower()
                    ).strip())
                    and f" {term_norm} " in normalized_question
                    for term in terms
                ):
                    require(*key, attribute.get("column_name"))

        for relationship in relationships:
            left = entity_by_id.get(relationship.get("from_entity_id"))
            right = entity_by_id.get(relationship.get("to_entity_id"))
            if left:
                require(left.get("schema_name"), left.get("table_name"), relationship.get("from_column"))
            if right:
                require(right.get("schema_name"), right.get("table_name"), relationship.get("to_column"))

        for metric in metrics:
            owner = entity_by_id.get(metric.get("entity_id"))
            if owner:
                attribute = next(
                    (
                        a for a in (owner.get("attributes") or [])
                        if (a.get("name") or "").lower() == (metric.get("attribute_name") or "").lower()
                    ),
                    None,
                )
                if attribute:
                    require(owner.get("schema_name"), owner.get("table_name"), attribute.get("column_name"))

        pruned_tables = []
        for table in tables:
            table_key = (table.schema_name, table.name)
            entity = next(
                (
                    e for e in entities
                    if (e.get("schema_name"), e.get("table_name")) == table_key
                ),
                None,
            )
            # No semantic entity/attributes means we lack enough governance to
            # safely prune; preserve all columns.
            if entity is None or not (entity.get("attributes") or []):
                pruned_tables.append(table)
                continue
            keep = required.get(table_key, set())
            columns = [col for col in table.columns if col.name.lower() in keep]
            # Never produce an unusable empty table context.
            if not columns:
                columns = table.columns
            pruned_tables.append(table.model_copy(update={"columns": columns}))

        logger.info(
            "query column_context=%s",
            {
                f"{t.schema_name}.{t.name}": [c.name for c in t.columns]
                for t in pruned_tables
            },
        )
        return SchemaMetadata(schema_name=None, tables=pruned_tables, dialect=self._database.dialect)

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

