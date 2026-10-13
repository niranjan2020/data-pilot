"""Relationship publication endpoint must not trust client-supplied proof."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from datapilot.api.routes import setup


class Metadata:
    def __init__(self, *, eligible=True):
        self.eligible = eligible
        self.calls = []

    async def get_active_data_source_id(self):
        return 7

    async def list_reviewed_relationships(self, source_id):
        return [{
            "from_schema": "demo", "from_table": "orders", "from_column": "customer_id",
            "to_schema": "demo", "to_table": "customers", "to_column": "id",
            "cardinality": "many_to_one", "review_status": "approved",
            "join_policy": "preserve_source", "description": "",
        }]

    async def publish_reviewed_relationship(self, source_id, review):
        self.calls.append((source_id, review))
        return self.eligible

    async def list_current_relationship_publications(self, source_id):
        return [{"from_table": "orders", "to_table": "customers"}]


def payload(**updates):
    values = {
        "from_schema": "demo", "from_table": "orders", "from_column": "customer_id",
        "to_schema": "demo", "to_table": "customers", "to_column": "id",
        "cardinality": "many_to_one", "review_status": "approved",
        "join_policy": "preserve_source",
    }
    values.update(updates)
    return setup.RelationshipReviewInput(**values)


def request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))


def test_publication_uses_persisted_review_and_verification(monkeypatch):
    metadata = Metadata()
    async def provider(_):
        return metadata, False
    monkeypatch.setattr(setup, "_setup_metadata", provider)
    result = asyncio.run(setup.publish_verified_relationship(7, payload(), request()))
    assert result["published"] is True
    assert len(metadata.calls) == 1


def test_publication_rejects_unverified_relationship(monkeypatch):
    metadata = Metadata(eligible=False)
    async def provider(_):
        return metadata, False
    monkeypatch.setattr(setup, "_setup_metadata", provider)
    with pytest.raises(HTTPException) as error:
        asyncio.run(setup.publish_verified_relationship(7, payload(), request()))
    assert error.value.status_code == 409


def test_publication_rejects_stale_policy(monkeypatch):
    metadata = Metadata()
    async def provider(_):
        return metadata, False
    monkeypatch.setattr(setup, "_setup_metadata", provider)
    with pytest.raises(HTTPException) as error:
        asyncio.run(setup.publish_verified_relationship(
            7, payload(join_policy="matched_only"), request()
        ))
    assert error.value.status_code == 409
    assert not metadata.calls


def test_current_publications_are_read_from_metadata(monkeypatch):
    metadata = Metadata()
    async def provider(_):
        return metadata, False
    monkeypatch.setattr(setup, "_setup_metadata", provider)
    result = asyncio.run(setup.get_relationship_publications(7, request()))
    assert result == [{"from_table": "orders", "to_table": "customers"}]
