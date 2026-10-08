"""Setup verification evidence endpoint regression tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from datapilot.api.routes import setup


REVIEW = {
    "from_schema": "astra", "from_table": "fixtures", "from_column": "vessel_id",
    "to_schema": "astra", "to_table": "vessels", "to_column": "id",
    "review_status": "approved", "cardinality": "many_to_one",
    "join_policy": "matched_only",
}


@pytest.mark.asyncio
async def test_verification_list_reports_current_evidence_without_activation(monkeypatch):
    metadata = SimpleNamespace(
        get_active_data_source_id=AsyncMock(return_value=7),
        list_reviewed_relationships=AsyncMock(return_value=[REVIEW]),
        get_relationship_verification=AsyncMock(return_value={"verified_at": "2026-10-08T10:00:00Z"}),
        close=AsyncMock(),
    )
    monkeypatch.setattr(setup, "_setup_metadata", AsyncMock(return_value=(metadata, True)))
    result = await setup.list_relationship_verifications(7, SimpleNamespace())
    assert len(result) == 1
    assert result[0]["verified"] is True
    assert result[0]["governed_join_active"] is False
    metadata.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_verification_list_marks_absent_evidence_unverified(monkeypatch):
    metadata = SimpleNamespace(
        get_active_data_source_id=AsyncMock(return_value=7),
        list_reviewed_relationships=AsyncMock(return_value=[REVIEW]),
        get_relationship_verification=AsyncMock(return_value=None),
        close=AsyncMock(),
    )
    monkeypatch.setattr(setup, "_setup_metadata", AsyncMock(return_value=(metadata, False)))
    result = await setup.list_relationship_verifications(7, SimpleNamespace())
    assert result[0]["verified"] is False
    assert result[0]["verification"] is None
    metadata.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_verification_list_rejects_inactive_datasource(monkeypatch):
    metadata = SimpleNamespace(
        get_active_data_source_id=AsyncMock(return_value=8),
        list_reviewed_relationships=AsyncMock(),
        get_relationship_verification=AsyncMock(),
        close=AsyncMock(),
    )
    monkeypatch.setattr(setup, "_setup_metadata", AsyncMock(return_value=(metadata, True)))
    with pytest.raises(HTTPException) as exc:
        await setup.list_relationship_verifications(7, SimpleNamespace())
    assert exc.value.status_code == 409
    metadata.get_relationship_verification.assert_not_awaited()
    metadata.close.assert_awaited_once()
