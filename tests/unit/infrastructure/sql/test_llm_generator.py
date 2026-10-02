"""Unit tests for the provider-independent LLM-backed SQL generator."""

import pytest

from datapilot.domain.models import SchemaMetadata
from datapilot.domain.query import SQLGeneration
from datapilot.infrastructure.sql.llm_generator import LLMBackedSQLGenerator


class FakeLLM:
    provider_name = "test-provider"

    async def generate_structured(self, messages, response_schema, temperature=0.0, **kwargs):
        assert response_schema is SQLGeneration
        assert messages[0].role == "system"
        assert "read-only" in messages[0].content
        return SQLGeneration(
            sql="SELECT COUNT(*) FROM records",
            explanation="Test generation",
        )


@pytest.mark.asyncio
async def test_generator_uses_only_generic_llm_contract():
    generator = LLMBackedSQLGenerator(FakeLLM())

    result = await generator.generate(
        question="How many records?",
        schema=SchemaMetadata(dialect="generic"),
        context={"intent": "count"},
        dialect="generic",
    )

    assert result == "SELECT COUNT(*) FROM records"
