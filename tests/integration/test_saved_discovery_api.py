"""Saved datasource discovery uses persisted credentials and safe API errors."""
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from datapilot.api.app import create_app
from datapilot.core.config import Settings


class FakeMetadata:
    async def save_schema(self, schema, data_source_id):
        assert data_source_id == 4


class FakeProvider:
    def __init__(self):
        self.close = AsyncMock()

    async def list_schemas(self):
        return ["public"]

    async def introspect_schema(self, name):
        assert name == "public"
        from datapilot.domain.models.schema import SchemaMetadata, TableMetadata
        return SchemaMetadata(schema_name="public", dialect="postgresql", tables=[
            TableMetadata(name="one", schema_name="public"),
            TableMetadata(name="two", schema_name="public"),
        ])


def test_discovery_uses_saved_connection_and_closes_it():
    app = create_app(settings=Settings(environment="test", metadata_database_url="postgresql://unused"))
    app.state.setup_metadata = FakeMetadata()
    provider = FakeProvider()
    with patch("datapilot.api.routes.setup.open_saved_data_source", new_callable=AsyncMock, return_value=provider) as open_connection:
        with TestClient(app) as client:
            response = client.post("/api/setup/data-source/4/discover")
    assert response.status_code == 200
    assert response.json() == {"data_source_id": 4, "schemas": ["public"], "tables": 2, "persisted": True}
    open_connection.assert_awaited_once()
    provider.close.assert_awaited_once()


def test_discovery_failure_does_not_expose_database_details():
    app = create_app(settings=Settings(environment="test", metadata_database_url="postgresql://unused"))
    app.state.setup_metadata = FakeMetadata()
    with patch("datapilot.api.routes.setup.open_saved_data_source", new_callable=AsyncMock, side_effect=RuntimeError("secret-password")):
        with TestClient(app) as client:
            response = client.post("/api/setup/data-source/4/discover")
    assert response.status_code == 422
    assert "secret-password" not in response.text
