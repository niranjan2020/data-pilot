"""LLM-backed SQL generator adapter.

This adapter is intentionally provider-agnostic. It depends only on the
LLMProvider protocol, so Gemini, OpenAI, Anthropic, local models, or a test
double can be substituted without changing the query orchestrator.
"""

from __future__ import annotations

from typing import Optional

from datapilot.core.exceptions import SQLGenerationError
from datapilot.domain.interfaces.llm import LLMProvider
from datapilot.domain.interfaces.sql_generator import SQLGenerator
from datapilot.domain.models import LLMMessage, SchemaMetadata
from datapilot.domain.query import SQLGeneration
from datapilot.domain.semantic import SemanticCatalog


class LLMBackedSQLGenerator(SQLGenerator):
    """Generate structured SQL using any configured LLMProvider."""

    def __init__(self, llm_provider: LLMProvider) -> None:
        self._llm = llm_provider

    async def generate(
        self,
        question: str,
        schema: SchemaMetadata,
        context: Optional[dict] = None,
        dialect: Optional[str] = None,
    ) -> str:
        result = await self.generate_structured(
            question=question,
            schema=schema,
            context=context,
            dialect=dialect,
        )
        return result.sql

    async def generate_structured(
        self,
        *,
        question: str,
        schema: SchemaMetadata,
        context: Optional[dict] = None,
        dialect: Optional[str] = None,
    ) -> SQLGeneration:
        messages = self.build_messages(
            question=question,
            schema=schema,
            context=context,
            dialect=dialect or schema.dialect,
        )

        try:
            return await self._llm.generate_structured(
                messages,
                SQLGeneration,
                temperature=0.0,
            )
        except Exception as exc:
            if isinstance(exc, SQLGenerationError):
                raise
            provider_details = getattr(exc, "details", None)
            raise SQLGenerationError(
                "Unable to generate SQL from the configured LLM provider",
                details={
                    "provider": self._llm.provider_name,
                    "cause_type": type(exc).__name__,
                    "cause": str(exc),
                    "provider_details": provider_details or {},
                },
            ) from exc

    def build_messages(
        self,
        *,
        question: str,
        schema: SchemaMetadata,
        context: Optional[dict] = None,
        dialect: Optional[str] = None,
    ) -> list[LLMMessage]:
        """Build the exact messages sent to the provider.

        Exposed for admin/query-trace diagnostics so the displayed prompt cannot
        drift from the prompt actually used for SQL generation.
        """
        return [
            LLMMessage(
                role="system",
                content=(
                    "You are a SQL generation component inside a database query engine. "
                    "Generate exactly one read-only SQL SELECT query. "
                    "Never generate INSERT, UPDATE, DELETE, MERGE, DDL, transaction control, "
                    "or multiple statements. Use only tables and columns present in the supplied "
                    "schema. The governed_semantic_context is authoritative for business meanings, "
                    "metric definitions, allowed physical entities, and join relationships. Prefer it over "
                    "raw retrieval results and never invent a join that conflicts with it. "
                    "When a selected metric has calculation_expression, use that governed row-level "
                    "expression exactly as the metric input and apply the configured aggregation around it; "
                    "do not replace it with a similarly named physical column. "
                    "Return the requested structured response."
                ),
            ),
            LLMMessage(
                role="user",
                content=self._build_prompt(
                    question=question,
                    schema=schema,
                    context=context,
                    dialect=dialect or schema.dialect,
                ),
            ),
        ]

    @staticmethod
    def _build_prompt(
        *,
        question: str,
        schema: SchemaMetadata,
        context: Optional[dict],
        dialect: str,
    ) -> str:
        return (
            f"User question:\n{question}\n\n"
            f"SQL dialect: {dialect}\n"
            f"Schema metadata:\n{schema.model_dump_json(exclude_none=True)}\n\n"
            f"Additional semantic/query context:\n{context or {}}\n\n"
            "Generate the safest, simplest SQL that answers the question."
        )
