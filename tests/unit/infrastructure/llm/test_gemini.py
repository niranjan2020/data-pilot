"""Unit tests for the Gemini LLM provider without network calls."""

import pytest
from pydantic import BaseModel

from datapilot.core.exceptions import LLMError
from datapilot.domain.models import LLMMessage
from datapilot.infrastructure.llm.gemini import GeminiLLMProvider


def test_provider_requires_api_key() -> None:
    with pytest.raises(LLMError):
        GeminiLLMProvider("")


def test_provider_name() -> None:
    # The SDK is only required at construction time; skip if unavailable.
    try:
        provider = GeminiLLMProvider("test-key")
    except LLMError as exc:
        if "not installed" in exc.message:
            pytest.skip("google-genai is not installed")
        raise
    assert provider.provider_name == "gemini"


class Answer(BaseModel):
    answer: str


@pytest.mark.asyncio
async def test_message_conversion_uses_native_system_instruction() -> None:
    try:
        provider = GeminiLLMProvider("test-key")
    except LLMError as exc:
        if "not installed" in exc.message:
            pytest.skip("google-genai is not installed")
        raise

    system_instruction, contents = provider._split_messages([
        LLMMessage(role="system", content="You are Data Pilot."),
        LLMMessage(role="user", content="How many vessels?"),
        LLMMessage(role="assistant", content="I need schema."),
    ])

    assert system_instruction == "You are Data Pilot."
    assert len(contents) == 2
    assert contents[0].role == "user"
    assert contents[1].role == "model"
