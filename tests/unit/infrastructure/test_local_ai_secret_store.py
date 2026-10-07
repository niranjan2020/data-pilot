import asyncio

from datapilot.domain.interfaces.ai_configuration import AIProviderKind, AIProviderSecretInput
from datapilot.infrastructure.secrets.local_env import LocalEnvAIProviderSecretStore


def test_local_secret_store_is_write_only_and_reports_presence(tmp_path):
    path = tmp_path / ".env"
    store = LocalEnvAIProviderSecretStore(str(path))
    secret = AIProviderSecretInput(api_key="super-secret-key")

    asyncio.run(store.put_ai_provider_secret(AIProviderKind.GEMINI, secret))

    assert asyncio.run(store.has_ai_provider_secret(AIProviderKind.GEMINI)) is True
    assert "GEMINI_API_KEY=super-secret-key" in path.read_text(encoding="utf-8")
    assert not hasattr(store, "get_ai_provider_secret")


def test_local_secret_store_updates_key_without_duplicate(tmp_path):
    path = tmp_path / ".env"
    path.write_text("GEMINI_API_KEY=old\nOTHER=value\n", encoding="utf-8")
    store = LocalEnvAIProviderSecretStore(str(path))

    asyncio.run(store.put_ai_provider_secret(
        AIProviderKind.GEMINI, AIProviderSecretInput(api_key="new")
    ))

    contents = path.read_text(encoding="utf-8")
    assert contents.count("GEMINI_API_KEY=") == 1
    assert "GEMINI_API_KEY=new" in contents
    assert "OTHER=value" in contents
