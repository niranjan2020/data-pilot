"""Integration tests for the natural-language query endpoint."""

from starlette.testclient import TestClient

from datapilot.api.app import create_app
from datapilot.api.routes.query import get_query_history_store, get_query_orchestrator
from datapilot.core.config import Settings
from datapilot.domain.query import QueryResponse


class FakeOrchestrator:
    async def query(self, request):
        return QueryResponse(
            question=request.question,
            status="completed",
            source="generator",
            sql="SELECT COUNT(*) FROM vessels",
            confidence=0.9,
        )


class FakeHistoryStore:
    def __init__(self):
        self.records = []

    async def record(self, request, response):
        self.records.append((request, response))
        return 1

    async def list(self, *, source_name=None, limit=50):
        return []

    async def get(self, history_id):
        return None


def test_query_endpoint_uses_orchestrator_contract_and_records_history():
    settings = Settings(
        app_name="Data Pilot Query Test",
        environment="test",
        default_database_url=None,
        gemini_api_key=None,
        openai_api_key=None,
        anthropic_api_key=None,
    )
    app = create_app(settings=settings)
    history = FakeHistoryStore()
    app.dependency_overrides[get_query_orchestrator] = lambda: FakeOrchestrator()
    app.dependency_overrides[get_query_history_store] = lambda: history

    with TestClient(app) as client:
        response = client.post(
            "/api/query",
            json={"question": "How many vessels are there?"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["source"] == "generator"
    assert data["sql"] == "SELECT COUNT(*) FROM vessels"
    assert len(history.records) == 1
