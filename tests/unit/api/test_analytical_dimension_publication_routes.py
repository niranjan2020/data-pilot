"""Analytical dimension publication API exposes approval separately from attributes."""
import asyncio

from datapilot.api.routes import semantic


class FakeProvider:
    async def get_data_source_id(self, source):
        return 7 if source == "demo" else None

    async def list_semantic_entities(self, source_id):
        return [{"id": 12, "name": "Vessel", "attributes": [
            {"name": "Operator", "column_name": "operator"},
            {"name": "Status", "column_name": "status"},
        ]}]

    async def list_published_analytical_dimensions(self, source_id):
        return [{"entity_id": 12, "name": "Operator", "column_name": "operator"}]

    async def close(self):
        pass


def test_publication_status_is_distinct_from_attribute_configuration(monkeypatch):
    monkeypatch.setattr(semantic, "provider", FakeProvider)
    result = asyncio.run(semantic.analytical_dimensions("demo"))
    assert result["attributes"] == [
        {"entity_id": 12, "entity_name": "Vessel", "attribute_name": "Operator",
         "column_name": "operator", "is_published": True},
        {"entity_id": 12, "entity_name": "Vessel", "attribute_name": "Status",
         "column_name": "status", "is_published": False},
    ]


def test_publication_request_requires_explicit_entity_and_attribute():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        semantic.AnalyticalDimensionPublicationRequest(
            source_name="demo", entity_id=0, attribute_name="Operator",
        )
