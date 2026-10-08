from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from datapilot.api.app import create_app
from datapilot.core.config import Settings
from datapilot.infrastructure.database.relationship_cardinality import CardinalityEvidence


REVIEW = dict(from_schema="demo", from_table="events", from_column="asset_id",
              to_schema="demo", to_table="assets", to_column="id",
              cardinality="many_to_one", review_status="approved", description="An asset has events")


class Metadata:
    async def get_active_data_source_id(self):
        return 4

    async def list_reviewed_relationships(self, source_id):
        return [dict(REVIEW)]

    async def get_selected_datasets(self, source_id):
        return [dict(schema_name="demo", table_name="events"), dict(schema_name="demo", table_name="assets")]

    async def list_catalog_tables(self, source_id):
        return [
            dict(schema_name="demo", table_name="events", columns=[dict(name="asset_id", data_type="integer", is_primary_key=False)]),
            dict(schema_name="demo", table_name="assets", columns=[dict(name="id", data_type="integer", is_primary_key=True)]),
        ]

    async def list_catalog_foreign_keys(self, source_id):
        return [dict(schema_name="demo", table_name="events", from_column="asset_id", referenced_table="assets", to_column="id")]


class Provider:
    async def close(self):
        pass


def app_with(metadata):
    app = create_app(settings=Settings(environment="test", metadata_database_url="postgresql://unused"))
    app.state.setup_metadata = metadata
    return app


def test_validated_relationship_is_still_not_published():
    with patch("datapilot.api.routes.setup.open_saved_data_source", new_callable=AsyncMock, return_value=Provider()), patch(
        "datapilot.api.routes.setup.verify_live_cardinality", new_callable=AsyncMock,
        return_value=CardinalityEvidence(True, True)
    ):
        with TestClient(app_with(Metadata())) as client:
            response = client.post("/api/setup/data-source/4/relationship-verification", json=REVIEW)
    assert response.status_code == 200
    assert response.json()["structurally_valid"] is True
    assert response.json()["live_cardinality_verified"] is True
    assert response.json()["cardinality_holds"] is True
    assert response.json()["publishable"] is False


def test_duplicate_keys_block_verification():
    with patch("datapilot.api.routes.setup.open_saved_data_source", new_callable=AsyncMock, return_value=Provider()), patch(
        "datapilot.api.routes.setup.verify_live_cardinality", new_callable=AsyncMock,
        return_value=CardinalityEvidence(True, False, reason="Duplicate join keys.")
    ):
        with TestClient(app_with(Metadata())) as client:
            response = client.post("/api/setup/data-source/4/relationship-verification", json=REVIEW)
    assert response.status_code == 200
    assert response.json()["cardinality_holds"] is False
    assert response.json()["publishable"] is False


def test_changed_review_is_rejected():
    with TestClient(app_with(Metadata())) as client:
        response = client.post("/api/setup/data-source/4/relationship-verification", json={**REVIEW, "cardinality": "one_to_one"})
    assert response.status_code == 409


def test_unselected_target_is_rejected():
    class MissingTarget(Metadata):
        async def get_selected_datasets(self, source_id):
            return [dict(schema_name="demo", table_name="events")]
    with TestClient(app_with(MissingTarget())) as client:
        response = client.post("/api/setup/data-source/4/relationship-verification", json=REVIEW)
    assert response.status_code == 409
