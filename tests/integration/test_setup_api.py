"""Integration contract for first-run setup status."""

from starlette.testclient import TestClient

from datapilot.api.app import create_app
from datapilot.core.config import Settings


class FakeSetupMetadata:
    def __init__(self, facts):
        self.facts = facts

    async def get_setup_facts(self):
        return dict(self.facts)


def test_setup_status_reads_persisted_facts_without_exposing_secrets():
    settings = Settings(
        environment="test",
        metadata_database_url="postgresql://platform-secret@localhost/catalog",
    )
    app = create_app(settings=settings)
    app.state.setup_metadata = FakeSetupMetadata({
        "ai_provider_ready": True,
        "data_source_ready": True,
        "data_selection_ready": False,
        "semantic_model_ready": False,
    })
    with TestClient(app) as client:
        response = client.get("/api/setup/status")

    assert response.status_code == 200
    assert response.json()["current_step"] == "data_selection"
    assert response.json()["ready"] is False
    assert "platform-secret" not in response.text


def test_setup_status_requires_platform_metadata_storage():
    app = create_app(settings=Settings(environment="test", metadata_database_url=None))
    with TestClient(app) as client:
        response = client.get("/api/setup/status")

    assert response.status_code == 503
    assert response.json()["detail"] == "Platform metadata storage is not configured."
