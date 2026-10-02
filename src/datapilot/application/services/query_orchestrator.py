"""Application service coordinating semantic matching, SQL generation, safety and execution."""

from __future__ import annotations

from typing import Any, Dict, Optional

from datapilot.application.services.semantic_matcher import SemanticMatcher
from datapilot.core.exceptions import SQLGenerationError, SQLValidationError
from datapilot.domain.interfaces.database import DatabaseProvider
from datapilot.domain.interfaces.llm import LLMProvider
from datapilot.domain.interfaces.semantic import SemanticCatalogProvider
from datapilot.domain.interfaces.sql_validator import SQLValidator
from datapilot.domain.models import LLMMessage, QueryResult, SchemaMetadata
from datapilot.domain.query import (
    AmbiguityCandidate,
    QueryRequest,
    QueryResponse,
    SQLGeneration,
)
from datapilot.domain.semantic import SemanticCatalog


class QueryOrchestrator:
    """Execute the complete core query workflow without exposing provider details.

    Template execution is deliberately parameter-explicit. A template that declares
    required parameters will not silently receive values guessed from free-form text.
    Questions that need inference fall through to structured LLM SQL generation.
    """

    def __init__(
        self,
        database_provider: DatabaseProvider,
        sql_validator: SQLValidator,
        llm_provider: LLMProvider,
        semantic_catalog_provider: SemanticCatalogProvider,
        *,
        semantic_matcher: Optional[SemanticMatcher] = None,
    ) -> None:
        self._database = database_provider
        self._validator = sql_validator
        self._llm = llm_provider
        self._semantic_catalog_provider = semantic_catalog_provider
        self._matcher = semantic_matcher or SemanticMatcher()

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
                message="More than one semantic template matches this question. Refine the question or provide explicit parameters.",
            )

        if match_result.matches:
            candidate = match_result.matches[0]
            template = candidate.template
            if self._has_all_required_parameters(template.required_parameters, request.parameters):
                sql = self._render_template(template.sql_template, request.parameters)
                return await self._validate_and_execute(
                    question=request.question,
                    sql=sql,
                    source="template",
                    confidence=candidate.score,
                    matched_template=template.name,
                )

        generated = await self._generate_sql(request.question, schema, catalog)
        return await self._validate_and_execute(
            question=request.question,
            sql=generated.sql,
            source="llm",
            confidence=0.0,
            matched_template=None,
            message=generated.explanation,
        )

    async def _generate_sql(
        self,
        question: str,
        schema: SchemaMetadata,
        catalog: SemanticCatalog,
    ) -> SQLGeneration:
        """Ask the LLM for structured SQL rather than free-form text."""
        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are Data Pilot's SQL generation engine. "
                    "Generate exactly one read-only SQL SELECT query for the supplied schema. "
                    "Never generate INSERT, UPDATE, DELETE, DDL, transaction control, or multiple statements. "
                    "Use only tables and columns present in the schema. "
                    "Return only the requested structured response."
                ),
            ),
            LLMMessage(
                role="user",
                content=self._build_generation_prompt(question, schema, catalog),
            ),
        ]
        try:
            return await self._llm.generate_structured(
                messages,
                SQLGeneration,
                temperature=0.0,
            )
        except Exception as exc:
            if isinstance(exc, SQLGenerationError):
                raise
            raise SQLGenerationError(
                "Unable to generate SQL from the natural-language question",
                details={"provider": self._llm.provider_name},
            ) from exc

    @staticmethod
    def _build_generation_prompt(
        question: str,
        schema: SchemaMetadata,
        catalog: SemanticCatalog,
    ) -> str:
        schema_payload = schema.model_dump_json(exclude_none=True)
        semantic_payload = catalog.model_dump_json(exclude_none=True)
        return (
            f"User question:\n{question}\n\n"
            f"Database dialect: {schema.dialect}\n"
            f"Schema metadata:\n{schema_payload}\n\n"
            f"Semantic catalog:\n{semantic_payload}\n\n"
            "Generate the safest, simplest SQL that answers the question."
        )

    async def _validate_and_execute(
        self,
        *,
        question: str,
        sql: str,
        source: str,
        confidence: float,
        matched_template: Optional[str],
        message: Optional[str] = None,
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
        result = await self._database.execute_query(executable_sql)

        return QueryResponse(
            question=question,
            status="completed",
            source=source,
            sql=executable_sql,
            result=result,
            confidence=confidence,
            matched_template=matched_template,
            validation_warnings=validation.warnings,
            message=message,
        )

    @staticmethod
    def _has_all_required_parameters(
        required_parameters: list[str],
        parameters: Dict[str, Any],
    ) -> bool:
        return all(
            parameter in parameters
            and parameters[parameter] is not None
            and str(parameters[parameter]).strip() != ""
            for parameter in required_parameters
        )

    @staticmethod
    def _render_template(sql_template: str, parameters: Dict[str, Any]) -> str:
        """Render named template placeholders with SQL-literal-safe values.

        This is intentionally conservative. Values are never interpolated as raw
        SQL identifiers or expressions; callers provide scalar parameter values only.
        """
        rendered = sql_template
        for name, value in parameters.items():
            placeholder = f"{{{{{name}}}}}"
            if placeholder not in rendered:
                continue
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
        text = str(value).replace("'", "''")
        return f"'{text}'"
