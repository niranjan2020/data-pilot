"""Concrete validation adapters for configured AI providers."""

from datapilot.domain.interfaces.ai_configuration import AIProviderConfiguration, AIProviderKind
from datapilot.infrastructure.llm.gemini import GeminiLLMProvider
from datapilot.infrastructure.secrets.local_env import LocalEnvAIProviderSecretStore
from datapilot.domain.models import LLMMessage


class ConfiguredAIProviderValidator:
    def __init__(self, secret_store: LocalEnvAIProviderSecretStore) -> None:
        self._secret_store = secret_store

    async def validate(self, configuration: AIProviderConfiguration) -> None:
        api_key = self._secret_store.resolve_for_runtime(configuration.provider)
        if not api_key:
            raise ValueError("AI provider credential is not configured")
        if configuration.provider is not AIProviderKind.GEMINI:
            raise ValueError(f"Provider validation is not implemented yet: {configuration.provider.value}")

        provider = GeminiLLMProvider(api_key=api_key, model=configuration.model)
        try:
            response = await provider.generate(
                [LLMMessage(role="user", content="Reply with OK.")],
                temperature=0.0,
                max_tokens=8,
            )
            if not response.content.strip():
                raise ValueError("AI provider returned an empty validation response")
        finally:
            await provider.close()
