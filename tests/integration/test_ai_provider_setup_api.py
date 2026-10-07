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
    assert metadata.facts == {}
