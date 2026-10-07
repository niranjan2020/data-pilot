"""Local environment-backed secret boundary for AI provider credentials.

This adapter is intentionally write-only for secret values: callers can store a key
and ask whether one exists, but cannot retrieve credential material through the
application contract. It is suitable for local OSS onboarding; managed deployments
can replace it with a vault-backed adapter without changing the domain contract.
"""

from pathlib import Path

from datapilot.domain.interfaces.ai_configuration import (
    AIProviderKind,
    AIProviderSecretInput,
)


_ENV_NAMES = {
    AIProviderKind.GEMINI: "GEMINI_API_KEY",
    AIProviderKind.OPENAI: "OPENAI_API_KEY",
    AIProviderKind.ANTHROPIC: "ANTHROPIC_API_KEY",
    AIProviderKind.AZURE_OPENAI: "AZURE_OPENAI_API_KEY",
}


class LocalEnvAIProviderSecretStore:
    def __init__(self, env_path: str = ".env") -> None:
        self._path = Path(env_path)

    async def put_ai_provider_secret(
        self, provider: AIProviderKind, secret: AIProviderSecretInput
    ) -> None:
        name = _ENV_NAMES[provider]
        value = secret.api_key.strip()
        lines = self._path.read_text(encoding="utf-8").splitlines() if self._path.exists() else []
        replacement = f"{name}={value}"
        updated: list[str] = []
        replaced = False
        for line in lines:
            if line.startswith(f"{name}="):
                updated.append(replacement)
                replaced = True
            else:
                updated.append(line)
        if not replaced:
            updated.append(replacement)
        self._path.write_text("\n".join(updated) + "\n", encoding="utf-8")

    async def has_ai_provider_secret(self, provider: AIProviderKind) -> bool:
        name = _ENV_NAMES[provider]
        if not self._path.exists():
            return False
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{name}="):
                return bool(line.split("=", 1)[1].strip())
        return False
