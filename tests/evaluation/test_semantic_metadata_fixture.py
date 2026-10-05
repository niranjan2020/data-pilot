import json
from pathlib import Path

import pytest

from datapilot.application.services.semantic_context import SemanticContextAssembler


FIXTURE = Path(__file__).parents[1] / "fixtures" / "semantic" / "metadata.json"


class FixtureMetadataProvider:
    def __init__(self):
        self.data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    async def get_data_source_id(self, source_name):
        return self.data["source"]["id"] if source_name == self.data["source"]["name"] else None

    async def list_semantic_datasets(self, source_id):
        return self.data["datasets"]

    async def list_semantic_entities(self, source_id):
        return self.data["entities"]

    async def list_semantic_relationships(self, source_id):
        return self.data["relationships"]

    async def list_semantic_metrics(self, source_id):
        return self.data["metrics"]

    async def list_business_rules(self, source_id):
        return self.data["business_rules"]

    async def list_time_dimensions(self, source_id):
        return self.data["time_dimensions"]


@pytest.mark.asyncio
async def test_versioned_metadata_fixture_resolves_cross_entity_metric_context():
    assembler = SemanticContextAssembler(FixtureMetadataProvider())

    context = await assembler.assemble(
        "Generic Commerce",
        [{
            "kind": "entity",
            "name": "Customer",
            "metadata": {"id": 201},
        }],
        "Show revenue by customer",
    )

    assert {entity["name"] for entity in context["entities"]} == {"Customer", "Order"}
    assert {metric["name"] for metric in context["metrics"]} == {"Revenue"}
    assert {relationship["name"] for relationship in context["relationships"]} == {
        "Order to Customer"
    }
    assert {
        f'{dataset["schema_name"]}.{dataset["table_name"]}'
        for dataset in context["datasets"]
    } == {"public.customers", "public.orders"}


@pytest.mark.asyncio
async def test_versioned_metadata_fixture_keeps_explicit_entity_query_metric_free():
    assembler = SemanticContextAssembler(FixtureMetadataProvider())

    context = await assembler.assemble(
        "Generic Commerce",
        [{
            "kind": "entity",
            "name": "Product",
            "metadata": {"id": 202},
        }],
        "Show products",
    )

    assert {entity["name"] for entity in context["entities"]} == {"Product"}
    assert context["metrics"] == []
    assert context["relationships"] == []
    assert {
        f'{dataset["schema_name"]}.{dataset["table_name"]}'
        for dataset in context["datasets"]
    } == {"public.products"}


@pytest.mark.asyncio
async def test_versioned_metadata_fixture_preserves_independent_explicit_entities():
    assembler = SemanticContextAssembler(FixtureMetadataProvider())

    context = await assembler.assemble(
        "Generic Commerce",
        [
            {"kind": "entity", "name": "Product", "metadata": {"id": 202}},
            {"kind": "entity", "name": "Customer", "metadata": {"id": 201}},
            {"kind": "metric", "name": "Revenue", "metadata": {"id": 401}},
        ],
        "Show revenue by product category and customer country",
    )

    assert {entity["name"] for entity in context["entities"]} == {
        "Customer", "Product", "Order"
    }
    assert {metric["name"] for metric in context["metrics"]} == {"Revenue"}
    assert {relationship["name"] for relationship in context["relationships"]} == {
        "Order to Customer", "Order to Product"
    }
    assert {
        f'{dataset["schema_name"]}.{dataset["table_name"]}'
        for dataset in context["datasets"]
    } == {"public.customers", "public.products", "public.orders"}


@pytest.mark.asyncio
async def test_versioned_metadata_fixture_keeps_same_entity_multi_dimension_context():
    assembler = SemanticContextAssembler(FixtureMetadataProvider())

    context = await assembler.assemble(
        "Generic Commerce",
        [
            {"kind": "entity", "name": "Customer", "metadata": {"id": 201}},
            {"kind": "metric", "name": "Revenue", "metadata": {"id": 401}},
        ],
        "Show revenue by customer country and customer segment",
    )

    assert {entity["name"] for entity in context["entities"]} == {"Customer", "Order"}
    assert {metric["name"] for metric in context["metrics"]} == {"Revenue"}
    assert {relationship["name"] for relationship in context["relationships"]} == {
        "Order to Customer"
    }
