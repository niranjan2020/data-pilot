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


def test_follow_up_prompt_requires_composition_not_plain_reinterpretation():
    generator = LLMBackedSQLGenerator(FakeLLM())

    messages = generator.build_messages(
        question="Only red products",
        schema=SchemaMetadata(dialect="postgresql"),
        context={
            "conversation_context": {
                "previous_question": "Show top 10 products by revenue",
                "governed_metrics": ["Revenue"],
                "governed_entities": ["Product", "Sales Order Line"],
            }
        },
        dialect="postgresql",
    )

    system = messages[0].content
    user = messages[1].content
    assert "Compose the current request as a delta" in system
    assert "preserve prior measures, grouping dimensions, ordering/ranking" in system
    assert "must not turn" in system
    assert "Show top 10 products by revenue" in user
    assert "Only red products" in user


def test_follow_up_prompt_composes_against_accumulated_analytical_intent():
    generator = LLMBackedSQLGenerator(FakeLLM())

    messages = generator.build_messages(
        question="Top 5 only",
        schema=SchemaMetadata(dialect="postgresql"),
        context={
            "conversation_context": {
                "previous_question": "Only red products",
                "analytical_turns": [
                    "Show top 10 products by revenue",
                    "Only red products",
                ],
                "governed_metrics": ["Revenue"],
                "governed_entities": ["Product", "Sales Order Line"],
            }
        },
        dialect="postgresql",
    )

    system = messages[0].content
    user = messages[1].content
    assert "accumulated analytical intent" in system
    assert "Show top 10 products by revenue" in user
    assert "Only red products" in user
    assert "Top 5 only" in user
