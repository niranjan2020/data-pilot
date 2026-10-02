"""Integration tests for the natural-language query endpoint."""

from starlette.testclient import TestClient

from datapilot.api.app import create_app
from datapilot.api.routes.query import get_query_orchestrator
from datapilot.core.config import Settings
from datapilot.domain.query import QueryResponse


class FakeOrchestrator:
    async def query(self, request):
        return QueryResponse(
            question=request.question,
            status="completed",
            source="template",
            sql="SELECT COUNT(*) FROM vessels",
            confidence=0.9,
            matched_template="VESSEL_COUNT",
        )


def test_query_endpoint_uses_orchestrator_contract():
    settings = Settings(
        app_name="Data Pilot Query Test",
        environment="test",
        default_database_url=None,
        gemini_api_key=None,
        openai_api_key=None,
        anthropic_api_key=None,
    )
    app = create_app(settings=settings)
    app.dependency_overrides[get_query_orchestrator] = lambda: FakeOrchestrator()

    with TestClient(app) as client:
        response = client.post(
            "/api/query",
            json={"question": "How many vessels are there?"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["source"] == "template"
    assert data["sql"] == "SELECT COUNT(*) FROM vessels"
    assert data["matched_template"] == "VESSEL_COUNT"
