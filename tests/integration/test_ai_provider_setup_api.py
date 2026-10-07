from starlette.testclient import TestClient

from datapilot.api.app import create_app
from datapilot.core.config import Settings
from datapilot.domain.interfaces.ai_configuration import AIProviderConfiguration


class FakeMetadata:
    def __init__(self):
        self.configuration = None
        self.facts = {}

    async def save_ai_provider_configuration(self, configuration):
        self.configuration = configuration.model_copy(update={"configured": True})
        return self.configuration

    async def get_ai_provider_configuration(self):
        return self.configuration

    async def update_setup_facts(self, **facts):
        self.facts.update(facts)
        return self.facts


class FakeValidator:
    def __init__(self, fails=False):
        self.fails = fails

    async def validate(self, configuration):
        if self.fails:
            raise RuntimeError("invalid provider configuration")


class FakeSecretStore:
    def __init__(self):
        self.providers = set()

    async def put_ai_provider_secret(self, provider, secret):
        assert secret.api_key
        self.providers.add(provider)

    async def has_ai_provider_secret(self, provider):
        return provider in self.providers


def test_ai_provider_setup_never_returns_secret_and_marks_ready():
    app = create_app(settings=Settings(environment="test", metadata_database_url="postgresql://unused"))
    metadata = FakeMetadata()
    secrets = FakeSecretStore()
    app.state.setup_metadata = metadata
    app.state.ai_secret_store = secrets
    app.state.ai_provider_validator = FakeValidator()

    with TestClient(app) as client:
        response = client.put("/api/setup/ai-provider", json={
            "provider": "openai",
            "model": "test-model",
            "api_key": "do-not-return-this",
        })
        read_response = client.get("/api/setup/ai-provider")

    assert response.status_code == 200
    assert response.json()["credential_configured"] is True
    assert "do-not-return-this" not in response.text
    assert "do-not-return-this" not in read_response.text
    assert read_response.json()["provider"] == "openai"
    assert metadata.facts["ai_provider_ready"] is True


def test_ai_provider_without_credential_does_not_mark_ready():
    app = create_app(settings=Settings(environment="test", metadata_database_url="postgresql://unused"))
    metadata = FakeMetadata()
    app.state.setup_metadata = metadata
    app.state.ai_secret_store = FakeSecretStore()

    with TestClient(app) as client:
        response = client.put("/api/setup/ai-provider", json={
            "provider": "anthropic",
            "model": "test-model",
        })

    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["credential_configured"] is False
    assert metadata.facts["ai_provider_ready"] is False


def test_ai_provider_validation_failure_does_not_advance_setup():
    app = create_app(settings=Settings(environment="test", metadata_database_url="postgresql://unused"))
    metadata = FakeMetadata()
    app.state.setup_metadata = metadata
    app.state.ai_secret_store = FakeSecretStore()
    app.state.ai_provider_validator = FakeValidator(fails=True)

    with TestClient(app) as client:
        response = client.put("/api/setup/ai-provider", json={
            "provider": "gemini",
            "model": "bad-model",
            "api_key": "invalid-key",
        })

    assert response.status_code == 422
    assert response.json()["detail"] == "AI provider validation failed."
    assert metadata.facts["ai_provider_ready"] is False
    assert "invalid-key" not in response.text


def test_switching_provider_invalidates_old_readiness_until_new_validation_passes():
    app = create_app(settings=Settings(environment="test", metadata_database_url="postgresql://unused"))
    metadata = FakeMetadata()
    metadata.facts["ai_provider_ready"] = True
    secrets = FakeSecretStore()
    app.state.setup_metadata = metadata
    app.state.ai_secret_store = secrets
    app.state.ai_provider_validator = FakeValidator(fails=True)

    with TestClient(app) as client:
        response = client.put("/api/setup/ai-provider", json={
            "provider": "openai",
            "model": "replacement-model",
            "api_key": "replacement-key",
        })

    assert response.status_code == 422
    assert metadata.configuration.provider.value == "openai"
    assert metadata.facts["ai_provider_ready"] is False
    assert "replacement-key" not in response.text
