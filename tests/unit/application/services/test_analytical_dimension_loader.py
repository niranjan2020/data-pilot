import pytest

from datapilot.application.services.analytical_dimension_loader import (
    load_published_analytical_dimensions,
)
from datapilot.application.services.analytical_dimensions import resolve_analytical_dimension


class Provider:
    async def get_data_source_id(self, name):
        return 7 if name == "sales" else None

    async def list_semantic_entities(self, source_id):
        return [
            {
                "id": 1, "name": "Customer", "schema_name": "Sales",
                "table_name": "Customer",
                "attributes": [
                    {"name": "Region", "column_name": "RegionCode"},
                    {"name": "Segment", "column_name": "SegmentCode"},
                ],
            },
            {
                "id": 2, "name": "Supplier", "schema_name": "Purchasing",
                "table_name": "Supplier",
                "attributes": [{"name": "Region", "column_name": "Region"}],
            },
        ]


class Store:
    def __init__(self, grants):
        self.grants = grants
        self.calls = []

    async def is_published(self, source_id, entity_id, attribute_name):
        self.calls.append((source_id, entity_id, attribute_name))
        return (source_id, entity_id, attribute_name) in self.grants


@pytest.mark.asyncio
async def test_only_explicit_attribute_grants_are_loaded():
    store = Store({(7, 1, "Region")})
    dimensions = await load_published_analytical_dimensions(
        provider=Provider(), datasource="sales", publication_store=store,
    )
    assert [(d.entity_name, d.name, d.column_name) for d in dimensions] == [
        ("Customer", "Region", "RegionCode"),
    ]
    assert len(store.calls) == 3


@pytest.mark.asyncio
async def test_entity_approval_does_not_approve_attributes():
    dimensions = await load_published_analytical_dimensions(
        provider=Provider(), datasource="sales", publication_store=Store(set()),
    )
    assert dimensions == ()


@pytest.mark.asyncio
async def test_published_duplicate_names_require_qualification():
    dimensions = await load_published_analytical_dimensions(
        provider=Provider(), datasource="sales",
        publication_store=Store({(7, 1, "Region"), (7, 2, "Region")}),
    )
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_analytical_dimension(dimensions, "Region")
    assert resolve_analytical_dimension(dimensions, "Supplier.Region").entity_id == 2


@pytest.mark.asyncio
async def test_unpublished_attribute_is_not_resolvable():
    dimensions = await load_published_analytical_dimensions(
        provider=Provider(), datasource="sales",
        publication_store=Store({(7, 1, "Region")}),
    )
    with pytest.raises(ValueError, match="Unknown"):
        resolve_analytical_dimension(dimensions, "Segment")


@pytest.mark.asyncio
async def test_unknown_datasource_rejected():
    with pytest.raises(ValueError, match="Unknown datasource"):
        await load_published_analytical_dimensions(
            provider=Provider(), datasource="unknown", publication_store=Store(set()),
        )


@pytest.mark.asyncio
async def test_missing_store_rejected():
    with pytest.raises(ValueError, match="publication store"):
        await load_published_analytical_dimensions(
            provider=Provider(), datasource="sales", publication_store=None,
        )


@pytest.mark.asyncio
async def test_store_failure_propagates():
    class BrokenStore:
        async def is_published(self, *args):
            raise RuntimeError("Database unavailable")

    with pytest.raises(RuntimeError, match="unavailable"):
        await load_published_analytical_dimensions(
            provider=Provider(), datasource="sales", publication_store=BrokenStore(),
        )


@pytest.mark.asyncio
async def test_non_boolean_store_result_does_not_grant():
    class BrokenStore:
        async def is_published(self, *args):
            return 1

    assert await load_published_analytical_dimensions(
        provider=Provider(), datasource="sales", publication_store=BrokenStore(),
    ) == ()
