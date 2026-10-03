"""Google Gemini implementation of the Data Pilot LLMProvider."""

from __future__ import annotations

from typing import Any, List, Optional, Type, TypeVar

from pydantic import BaseModel

from datapilot.core.exceptions import LLMError
from datapilot.domain.models import LLMMessage, LLMResponse

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

T = TypeVar("T", bound=BaseModel)


class GeminiLLMProvider:
    """Async Gemini adapter isolated behind the provider protocol."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        if not api_key:
            raise LLMError("Gemini API key is required")
        if genai is None:
            raise LLMError("google-genai is not installed; install Data Pilot dependencies before using Gemini")
        self._model = model
        self._client = genai.Client(api_key=api_key)

    @property
    def provider_name(self) -> str:
        return "gemini"

    @staticmethod
    def _split_messages(messages: List[LLMMessage]) -> tuple[Optional[str], List[types.Content]]:
        """Map Data Pilot roles to Gemini contents and native system instruction."""
        system_parts = [message.content for message in messages if message.role == "system"]
        contents: List[types.Content] = []

        for message in messages:
            if message.role == "system":
                continue
            role = "model" if message.role == "assistant" else "user"
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=message.content)],
                )
            )

        system_instruction = "\n\n".join(system_parts) or None
        return system_instruction, contents

    async def generate(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        stop_sequences: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        try:
            system_instruction, contents = self._split_messages(messages)
            config = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                stop_sequences=stop_sequences,
                system_instruction=system_instruction,
            )
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )
            usage = getattr(response, "usage_metadata", None)
            token_usage = None
            if usage is not None:
                token_usage = {
                    key: value
                    for key, value in {
                        "prompt_tokens": getattr(usage, "prompt_token_count", None),
                        "completion_tokens": getattr(usage, "candidates_token_count", None),
                        "total_tokens": getattr(usage, "total_token_count", None),
                    }.items()
                    if value is not None
                }
            return LLMResponse(
                content=response.text or "",
                model_name=self._model,
                token_usage=token_usage,
            )
        except Exception as exc:
            raise LLMError(
                "Gemini text generation failed",
                details={"model": self._model, "error_type": type(exc).__name__},
            ) from exc

    async def generate_structured(
        self,
        messages: List[LLMMessage],
        response_schema: Type[T],
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> T:
        try:
            system_instruction, contents = self._split_messages(messages)
            config = types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type="application/json",
                response_schema=response_schema,
                system_instruction=system_instruction,
            )
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )
            if not response.text:
                raise LLMError("Gemini returned an empty structured response")
            return response_schema.model_validate_json(response.text)
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(
                "Gemini structured generation failed",
                details={
                    "model": self._model,
                    "schema": response_schema.__name__,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            ) from exc

    async def close(self) -> None:
        """Release provider resources when supported by the SDK."""
        close = getattr(self._client, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result
