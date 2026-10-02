"""Integration tests verifying application startup, health probes, and API routes."""

from starlette.testclient import TestClient


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
    """Verify GET /health/ready returns comprehensive diagnostics and component states."""
    response = client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app"] == "Data Pilot Test"
    assert data["environment"] == "test"
    assert "system" in data
    assert "components" in data
    assert data["components"]["database"]["status"] == "configured"
    assert data["components"]["llm"]["status"] == "configured"


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
