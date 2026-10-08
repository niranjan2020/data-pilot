"""Regression tests for PostgreSQL first-run connection checks."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from datapilot.api.app import create_app
from datapilot.core.config import Settings


def test_data_source_connection_test_does_not_persist_or_return_credentials():
    app = create_app(settings=Settings(environment="test", metadata_database_url=None))
    payload = {
        "name": "Demo", "host": "postgres", "port": 5432,
        "database": "demo", "username": "reader", "password": "private-password",
        "sslmode": "prefer",
    }
    with patch(
        "datapilot.api.routes.setup.test_postgresql_connection",
        new_callable=AsyncMock,
        return_value=True,
    ) as check:
        with TestClient(app) as client:
            response = client.post("/api/setup/data-source/test", json=payload)
    assert response.status_code == 200
    assert response.json() == {"connected": True}
    assert "private-password" not in response.text
    check.assert_awaited_once()


def test_data_source_connection_failure_is_safe():
    app = create_app(settings=Settings(environment="test", metadata_database_url=None))
    payload = {
        "name": "Demo", "host": "postgres", "port": 5432,
        "database": "demo", "username": "reader", "password": "private-password",
        "sslmode": "prefer",
    }
    with patch(
        "datapilot.api.routes.setup.test_postgresql_connection",
        new_callable=AsyncMock,
        side_effect=RuntimeError("private-password secret failure"),
    ):
        with TestClient(app) as client:
            response = client.post("/api/setup/data-source/test", json=payload)
    assert response.status_code == 422
    assert "private-password" not in response.text
