from datapilot.api.app import create_app
from datapilot.core.config import Settings
from datapilot.infrastructure.llm.validation import ConfiguredAIProviderValidator
from datapilot.infrastructure.secrets.local_env import LocalEnvAIProviderSecretStore


def test_application_composes_local_ai_onboarding_adapters():
    app = create_app(settings=Settings(environment="test"))

    assert isinstance(app.state.ai_secret_store, LocalEnvAIProviderSecretStore)
    assert isinstance(app.state.ai_provider_validator, ConfiguredAIProviderValidator)


def test_windows_asyncio_policy_uses_selector_for_psycopg(monkeypatch):
    import asyncio
    import datapilot.api.app as app_module

    if not hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        return

    monkeypatch.setattr(app_module.sys, "platform", "win32")
    app_module._configure_windows_asyncio_policy()

    assert isinstance(
        asyncio.get_event_loop_policy(),
        asyncio.WindowsSelectorEventLoopPolicy,
    )
