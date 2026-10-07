"""Integration contract for first-run setup status."""

from starlette.testclient import TestClient

from datapilot.api.app import create_app
from datapilot.core.config import Settings


class FakeSetupMetadata:
    def __init__(self, facts):
        self.facts = facts

    async def get_setup_facts(self):
        return dict(self.facts)

    async def update_setup_facts(self, **facts):
        self.facts.update(facts)
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


def test_product_readiness_uses_persisted_setup_facts_not_environment_presence():
    settings = Settings(
        environment="test",
        metadata_database_url="postgresql://unused",
        default_database_url="postgresql://configured-but-not-approved",
        gemini_api_key="configured-but-not-validated",
    )
    app = create_app(settings=settings)
    app.state.setup_metadata = FakeSetupMetadata({
        "ai_provider_ready": False,
        "data_source_ready": False,
        "data_selection_ready": False,
        "semantic_model_ready": False,
    })
    with TestClient(app) as client:
        response = client.get("/api/setup/readiness")

    assert response.status_code == 200
    assert response.json() == {
        "ready": False,
        "setup_ready": False,
        "metadata_storage": "ready",
        "ai_provider": "not_ready",
        "data_source": "not_ready",
    }


def test_setup_progress_resumes_from_persisted_facts_after_app_restart():
    persisted = FakeSetupMetadata({
        "ai_provider_ready": True,
        "data_source_ready": True,
        "data_selection_ready": False,
        "semantic_model_ready": False,
    })

    first_app = create_app(settings=Settings(environment="test", metadata_database_url="postgresql://unused"))
    first_app.state.setup_metadata = persisted
    with TestClient(first_app) as client:
        first = client.get("/api/setup/status")

    second_app = create_app(settings=Settings(environment="test", metadata_database_url="postgresql://unused"))
    second_app.state.setup_metadata = persisted
    with TestClient(second_app) as client:
        resumed = client.get("/api/setup/status")

    assert first.status_code == 200
    assert resumed.status_code == 200
    assert resumed.json() == first.json()
    assert resumed.json()["current_step"] == "data_selection"
    assert resumed.json()["first_run"] is True


def test_setup_resume_recomputes_current_step_from_persisted_facts():
    persisted = FakeSetupMetadata({
        "ai_provider_ready": True,
        "data_source_ready": True,
        "data_selection_ready": False,
        "semantic_model_ready": False,
    })
    app = create_app(settings=Settings(environment="test", metadata_database_url="postgresql://unused"))
    app.state.setup_metadata = persisted

    with TestClient(app) as client:
        before = client.get("/api/setup/status")
        persisted.facts["data_selection_ready"] = True
        after = client.get("/api/setup/status")

    assert before.json()["current_step"] == "data_selection"
    assert after.json()["current_step"] == "semantic_review"
    assert after.json()["ready"] is False
