"""Application service coordinating semantic matching, SQL generation, safety and execution."""

from __future__ import annotations

from typing import Any, Dict, Optional

from datapilot.application.services.entity_resolver import DeterministicEntityResolver
from datapilot.application.services.semantic_matcher import SemanticMatcher
from datapilot.core.exceptions import SQLValidationError
from datapilot.domain.interfaces.database import DatabaseProvider
from datapilot.domain.interfaces.entity_resolver import EntityResolver
from datapilot.domain.interfaces.query_policy import QueryPolicyEnforcer
from datapilot.domain.interfaces.semantic import SemanticCatalogProvider
from datapilot.domain.interfaces.sql_generator import SQLGenerator
from datapilot.domain.interfaces.sql_validator import SQLValidator
from datapilot.domain.models import SchemaMetadata
from datapilot.domain.policies import QueryExecutionPolicy
from datapilot.domain.query import AmbiguityCandidate, QueryRequest, QueryResponse
from datapilot.domain.semantic import QueryIntent, SemanticCatalog
from datapilot.infrastructure.sql.query_policy import SQLQueryPolicyEnforcer


class QueryOrchestrator:
    """Execute the core query workflow independently of any LLM vendor."""

    def __init__(
        self,
        database_provider: DatabaseProvider,
        sql_validator: SQLValidator,
        sql_generator: SQLGenerator,
        semantic_catalog_provider: SemanticCatalogProvider,
        *,
        semantic_matcher: Optional[SemanticMatcher] = None,
        entity_resolver: Optional[EntityResolver] = None,
        query_policy_enforcer: Optional[QueryPolicyEnforcer] = None,
        query_policy: Optional[QueryExecutionPolicy] = None,
        query_timeout_seconds: Optional[float] = None,
    ) -> None:
        self._database = database_provider
        self._validator = sql_validator
        self._sql_generator = sql_generator
        self._semantic_catalog_provider = semantic_catalog_provider
        self._matcher = semantic_matcher or SemanticMatcher()
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
        schema = schema or await self._database.introspect_schema()
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
        match_result = self._matcher.match_templates(request.question, catalog)

        if match_result.is_ambiguous:
            candidates = [
                AmbiguityCandidate(
                    name=item.template.name,
                    description=item.template.description,
                    score=item.score,
                    matched_terms=list(item.matched_terms),
                )
                for item in match_result.matches[:5]
            ]
            return QueryResponse(
                question=request.question,
                status="ambiguous",
                confidence=match_result.confidence,
                ambiguity_candidates=candidates,
                resolved_intent=intent,
                message="More than one semantic template matches this question. Refine the question or provide explicit parameters.",
            )

        if match_result.matches:
            candidate = match_result.matches[0]
            template = candidate.template
            if self._has_all_required_parameters(template.required_parameters, parameters):
                sql = self._render_template(template.sql_template, parameters)
                return await self._validate_and_execute(
                    question=request.question,
                    sql=sql,
                    source="template",
                    confidence=candidate.score,
                    matched_template=template.name,
                    resolved_intent=intent,
                )

        generated = await self._sql_generator.generate(
            question=request.question,
            schema=schema,
            context={
                "semantic_catalog": catalog.model_dump(mode="json"),
                "query_intent": intent.model_dump(mode="json"),
                "parameters": parameters,
            },
            dialect=self._database.dialect,
        )
        return await self._validate_and_execute(
            question=request.question,
            sql=generated,
            source="generator",
            confidence=intent.confidence,
            matched_template=None,
            resolved_intent=intent,
        )

    async def _validate_and_execute(
        self,
        *,
        question: str,
        sql: str,
        source: str,
        confidence: float,
        matched_template: Optional[str],
        resolved_intent: Optional[QueryIntent] = None,
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

        result = await self._database.execute_query(
            policy_result.sql,
            timeout_seconds=self._query_policy.timeout_seconds,
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
            matched_template=matched_template,
            resolved_intent=resolved_intent,
            validation_warnings=[*validation.warnings, *policy_result.warnings],
        )

    @staticmethod
    def _merge_resolved_parameters(
        parameters: Dict[str, Any],
        intent: QueryIntent,
    ) -> Dict[str, Any]:
        """Fill missing template parameters from deterministic semantic filters."""
        merged = dict(parameters)
        for item in intent.filters:
            for key in (item.attribute, item.column_name):
                if key not in merged:
                    merged[key] = item.value
        return merged

    @staticmethod
    def _has_all_required_parameters(required_parameters: list[str], parameters: Dict[str, Any]) -> bool:
        return all(
            parameter in parameters
            and parameters[parameter] is not None
            and str(parameters[parameter]).strip() != ""
            for parameter in required_parameters
        )

    @staticmethod
    def _render_template(sql_template: str, parameters: Dict[str, Any]) -> str:
        """Render named scalar placeholders with SQL-literal-safe values."""
        rendered = sql_template
        for name, value in parameters.items():
            placeholder = f"{{{{{name}}}}}"
            if placeholder in rendered:
                rendered = rendered.replace(placeholder, QueryOrchestrator._sql_literal(value))
        return rendered

    @staticmethod
    def _sql_literal(value: Any) -> str:
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        if value is None:
            return "NULL"
        return f"'{str(value).replace(chr(39), chr(39) + chr(39))}'"
