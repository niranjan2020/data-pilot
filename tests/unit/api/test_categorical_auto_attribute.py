"""Explicit approval is forwarded to governed categorical publication."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from datapilot.api.routes.setup import (
    ApprovedCategoricalMapping,
    PublishCategoricalMappingsRequest,
    publish_saved_source_categorical_mappings,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [True, False])
async def test_attribute_creation_requires_explicit_flag(approved):
    metadata = AsyncMock()
    metadata.get_active_data_source_id.return_value = 9
    metadata.get_selected_datasets.return_value = [
        {"schema_name": "astra", "table_name": "vessels"}
    ]
    metadata.list_catalog_tables.return_value = [{
        "schema_name": "astra", "table_name": "vessels",
        "columns": [{"name": "vessel_segment", "data_type": "text"}],
    }]
    metadata.publish_categorical_mappings.return_value = 1
    provider = AsyncMock()
    provider.propose_categorical_values.return_value = {
        "complete": True, "values": ["A-FDR"],
    }
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        data_source_secret_store=object()
    )))
    payload = PublishCategoricalMappingsRequest(
        schema_name="astra", table_name="vessels", column_name="vessel_segment",
        mappings=[ApprovedCategoricalMapping(canonical_value="A-FDR")],
        create_missing_attribute=approved,
    )
    with patch("datapilot.api.routes.setup._setup_metadata",
               new=AsyncMock(return_value=(metadata, False))), \
         patch("datapilot.api.routes.setup.open_saved_data_source",
               new=AsyncMock(return_value=provider)):
        result = await publish_saved_source_categorical_mappings(9, payload, request)
    assert result["published"] is True
    assert metadata.publish_categorical_mappings.await_args.kwargs[
        "create_missing_attribute"
    ] is approved
