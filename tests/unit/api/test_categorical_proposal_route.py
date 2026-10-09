"""C4 proposal endpoint authorization and fail-closed guards."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from datapilot.api.routes.setup import CategoricalProposalRequest, propose_saved_source_categorical_values


def request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(data_source_secret_store=object())))


def metadata():
    m = AsyncMock()
    m.get_active_data_source_id.return_value = 9
    m.get_selected_datasets.return_value = [{"schema_name": "astra", "table_name": "vessels"}]
    m.list_catalog_tables.return_value = [{
        "schema_name": "astra", "table_name": "vessels",
        "columns": [{"name": "vessel_status", "data_type": "text"}],
    }]
    return m


@pytest.mark.asyncio
async def test_categorical_proposal_requires_selected_dataset():
    m = metadata()
    with patch("datapilot.api.routes.setup._setup_metadata", new=AsyncMock(return_value=(m, False))):
        with pytest.raises(HTTPException) as exc:
            await propose_saved_source_categorical_values(9, CategoricalProposalRequest(
                schema_name="astra", table_name="unapproved", column_name="vessel_status"), request())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_categorical_proposal_rejects_nontext_column():
    m = metadata()
    m.list_catalog_tables.return_value[0]["columns"][0]["data_type"] = "integer"
    with patch("datapilot.api.routes.setup._setup_metadata", new=AsyncMock(return_value=(m, False))):
        with pytest.raises(HTTPException) as exc:
            await propose_saved_source_categorical_values(9, CategoricalProposalRequest(
                schema_name="astra", table_name="vessels", column_name="vessel_status"), request())
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_categorical_proposal_returns_unpublished_values():
    m = metadata()
    provider = AsyncMock()
    provider.propose_categorical_values.return_value = {
        "status": "proposed", "values": ["ON ORDER", "DELIVERED"], "complete": True,
    }
    with patch("datapilot.api.routes.setup._setup_metadata", new=AsyncMock(return_value=(m, False))), \
         patch("datapilot.api.routes.setup.open_saved_data_source", new=AsyncMock(return_value=provider)):
        result = await propose_saved_source_categorical_values(9, CategoricalProposalRequest(
            schema_name="astra", table_name="vessels", column_name="vessel_status"), request())
    assert result["published"] is False
    assert result["values"] == ["ON ORDER", "DELIVERED"]
    provider.propose_categorical_values.assert_awaited_once_with(
        "astra", "vessels", "vessel_status", max_values=50, timeout_seconds=2.0)
    provider.close.assert_awaited_once()
