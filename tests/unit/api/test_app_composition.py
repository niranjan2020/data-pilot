from datapilot.api.app import create_app
from datapilot.core.config import Settings
from datapilot.infrastructure.llm.validation import ConfiguredAIProviderValidator
from datapilot.infrastructure.secrets.local_env import LocalEnvAIProviderSecretStore


def test_application_composes_local_ai_onboarding_adapters():
    app = create_app(settings=Settings(environment="test"))

    assert isinstance(app.state.ai_secret_store, LocalEnvAIProviderSecretStore)
    assert isinstance(app.state.ai_provider_validator, ConfiguredAIProviderValidator)
