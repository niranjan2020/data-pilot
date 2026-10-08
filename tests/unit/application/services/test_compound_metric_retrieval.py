"""Regression: compound filter/dimension questions retain the unique governed metric."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from datapilot.application.services.semantic_context import SemanticContextAssembler


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [
    "How many vessels are there?",
    "How many vessels does MSC have?",
    "How many on order and delivered vessels does MSC have?",
])
async def test_unique_entity_metric_is_resolved_for_compound_count(question):
    entity = {
        "id": 1, "name": "Vessel", "synonyms": ["ship"],
        "schema_name": "astra", "table_name": "vessels",
    }
    metric = {
        "id": 2, "name": "Vessel Count", "synonyms": ["number of vessels"],
        "entity_id": 1, "aggregation": "count_distinct",
    }
    metadata = SimpleNamespace(
        get_data_source_id=AsyncMock(return_value=3),
        list_semantic_datasets=AsyncMock(return_value=[]),
        list_semantic_entities=AsyncMock(return_value=[entity]),
        list_semantic_relationships=AsyncMock(return_value=[]),
        list_semantic_metrics=AsyncMock(return_value=[metric]),
        list_business_rules=AsyncMock(return_value=[]),
        list_time_dimensions=AsyncMock(return_value=[]),
    )
    result = await SemanticContextAssembler(metadata).assemble("astra-dev", [], question)
    assert [item["name"] for item in result["metrics"]] == ["Vessel Count"]
    assert [item["name"] for item in result["entities"]] == ["Vessel"]
    assert result["datasets"][0]["schema_name"] == "astra"


@pytest.mark.asyncio
async def test_multiple_entity_metrics_are_not_guessed():
    entity = {"id": 1, "name": "Vessel", "synonyms": [], "schema_name": "astra", "table_name": "vessels"}
    metrics = [
        {"id": 2, "name": "Vessel Count", "entity_id": 1, "synonyms": []},
        {"id": 3, "name": "Active Vessel Count", "entity_id": 1, "synonyms": []},
    ]
    metadata = SimpleNamespace(
        get_data_source_id=AsyncMock(return_value=3),
        list_semantic_datasets=AsyncMock(return_value=[]),
        list_semantic_entities=AsyncMock(return_value=[entity]),
        list_semantic_relationships=AsyncMock(return_value=[]),
        list_semantic_metrics=AsyncMock(return_value=metrics),
        list_business_rules=AsyncMock(return_value=[]),
        list_time_dimensions=AsyncMock(return_value=[]),
    )
    result = await SemanticContextAssembler(metadata).assemble(
        "astra-dev", [], "How many vessels are there?"
    )
    assert result["metrics"] == []
