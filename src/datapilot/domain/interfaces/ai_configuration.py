"""Provider-independent AI setup configuration contracts.

These models intentionally contain no credentials. Provider secrets cross a separate
write-only boundary and must never be returned by normal configuration APIs.
"""

from enum import Enum
from typing import Protocol

from pydantic import BaseModel, Field


class AIProviderKind(str, Enum):
    GEMINI = "gemini"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE_OPENAI = "azure_openai"


class AIProviderConfiguration(BaseModel):
    provider: AIProviderKind
    model: str = Field(min_length=1)
    endpoint: str | None = None
    configured: bool = False
    credential_configured: bool = False


class AIProviderSecretInput(BaseModel):
    api_key: str = Field(min_length=1)


class AIProviderConfigurationStore(Protocol):
    async def get_ai_provider_configuration(self) -> AIProviderConfiguration | None:
        """Return safe provider configuration without credential material."""
        ...

    async def save_ai_provider_configuration(
        self, configuration: AIProviderConfiguration
    ) -> AIProviderConfiguration:
        """Persist only non-secret provider configuration."""
        ...


class AIProviderSecretStore(Protocol):
    async def put_ai_provider_secret(
        self, provider: AIProviderKind, secret: AIProviderSecretInput
    ) -> None:
        """Persist provider credential through a write-only secret boundary."""
        ...

    async def has_ai_provider_secret(self, provider: AIProviderKind) -> bool:
        """Report credential presence without returning credential material."""
        ...
