"""Integration tests verifying application startup, health probes, and API routes."""

from starlette.testclient import TestClient
from datapilot.api.app import create_app


def test_root_endpoint(client: TestClient):
    """Verify that root endpoint provides friendly metadata and links."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "operational"
    assert data["name"] == "Data Pilot Test"
    assert "documentation" in data
    assert "health" in data


def test_health_liveness_endpoint(client: TestClient):
    """Verify GET /health returns status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "Data Pilot Test"
    assert data["version"] == "0.1.0-test"
    assert "timestamp" in data


def test_health_readiness_endpoint(client: TestClient):
    """Verify readiness reports the explicitly composed runtime checker."""
    from datapilot.domain.interfaces.runtime_health import RuntimeComponentHealth

    class HealthyRuntimeChecker:
        async def check(self):
            return {"metadata": RuntimeComponentHealth(status="healthy", details={"reachable": True})}

    client.app.state.runtime_health_checker = HealthyRuntimeChecker()
    response = client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app"] == "Data Pilot Test"
    assert data["environment"] == "test"
    assert "system" in data
    assert "components" in data
    assert data["components"]["metadata"]["status"] == "healthy"
    # Ensure no secret API key values are leaked into health output
    assert "test-gemini-key" not in response.text


def test_health_readiness_unconfigured_components():
    """Verify GET /health/ready correctly marks missing database/LLM config as unconfigured."""
    from datapilot.core.config import Settings
    unconfigured_settings = Settings(
        app_name="Data Pilot Minimal",
        environment="test",
        default_database_url=None,
        gemini_api_key=None,
        openai_api_key=None,
        anthropic_api_key=None,
    )
    app = create_app(settings=unconfigured_settings)
    with TestClient(app) as unconfigured_client:
        response = unconfigured_client.get("/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["components"]["metadata"]["status"] == "degraded"
        assert data["components"]["metadata"]["details"]["reason"] == "metadata_not_configured"


def test_info_endpoint(client: TestClient):
    """Verify GET /info returns architecture details and supported dialects."""
    response = client.get("/info")
    assert response.status_code == 200
    data = response.json()
    assert data["app"] == "Data Pilot Test"
    assert "postgresql" in data["supported_database_dialects"]
    assert "gemini" in data["supported_llm_providers"]
    assert data["architecture"]["db_agnostic"] is True
    assert data["architecture"]["llm_agnostic"] is True


def test_openapi_schema(client: TestClient):
    """Verify OpenAPI documentation schema is generated and accessible."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "paths" in schema
    assert "/health" in schema["paths"]
    assert "/health/ready" in schema["paths"]
    assert "/info" in schema["paths"]


def test_swagger_docs(client: TestClient):
    """Verify Swagger UI docs endpoint loads."""
    response = client.get("/docs")
    assert response.status_code == 200


def test_health_readiness_uses_runtime_checker_not_static_settings():
    from datapilot.core.config import Settings
    from datapilot.domain.interfaces.runtime_health import RuntimeComponentHealth

    class FakeRuntimeChecker:
        async def check(self):
            return {
                "metadata": RuntimeComponentHealth(status="healthy", details={"reachable": True}),
                "database": RuntimeComponentHealth(status="unhealthy", details={"reachable": False}),
            }

    app = create_app(settings=Settings(
        environment="test",
        default_database_url="postgresql://configured",
        gemini_api_key="configured-key",
    ))
    app.state.runtime_health_checker = FakeRuntimeChecker()

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["components"]["metadata"]["status"] == "healthy"
    assert data["components"]["database"]["status"] == "unhealthy"
    assert "configured-key" not in response.text
