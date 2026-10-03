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
        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are a SQL generation component inside a database query engine. "
                    "Generate exactly one read-only SQL SELECT query. "
                    "Never generate INSERT, UPDATE, DELETE, MERGE, DDL, transaction control, "
                    "or multiple statements. Use only tables and columns present in the supplied "
                    "schema. Use retrieved governed semantic context for business meanings, "
                    "metric definitions, and join relationships. Return the requested structured response."
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
                "Unable to generate SQL from the configured LLM provider",
                details={"provider": self._llm.provider_name},
            ) from exc

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
