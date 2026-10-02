"""LLM provider abstraction interface.

Defines the contract for language model providers (Google Gemini, OpenAI, Anthropic,
or local models). The application logic interacts exclusively through this protocol.
"""

from typing import Any, Dict, List, Optional, Protocol, Type, TypeVar, runtime_checkable
from pydantic import BaseModel
from datapilot.domain.models import LLMMessage, LLMResponse

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers.

    All LLM integrations must satisfy this interface to be swappable without altering
    the core orchestration or prompt assembly logic.
    """

    @property
    def provider_name(self) -> str:
        """Return the unique identifier for this provider (e.g., 'gemini', 'openai')."""
        ...

    async def generate(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        stop_sequences: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a freeform text response given a prompt / list of messages."""
        ...

    async def generate_structured(
        self,
        messages: List[LLMMessage],
        response_schema: Type[T],
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> T:
        """Generate a structured response parsed directly into the target Pydantic model."""
        ...
