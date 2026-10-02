"""Pytest configuration and shared fixtures for unit and integration testing."""

import pytest
from starlette.testclient import TestClient
from datapilot.api.app import create_app
from datapilot.core.config import Settings


@pytest.fixture
def test_settings() -> Settings:
    """Fixture providing isolated test settings."""
    return Settings(
        app_name="Data Pilot Test",
        app_version="0.1.0-test",
        environment="test",
        debug=True,
        log_level="CRITICAL",  # Suppress logs during tests
        default_database_url="postgresql://test_user:test_pass@localhost:5432/test_db",
        default_llm_provider="gemini",
        gemini_api_key="test-gemini-key",
    )


@pytest.fixture
def client(test_settings: Settings) -> TestClient:
    """Fixture providing a synchronous HTTP test client for the FastAPI application."""
    app = create_app(settings=test_settings)
    with TestClient(app) as test_client:
        yield test_client
