import pytest

from datapilot.application.services.analytical_plan import (
    AnalyticalOperation, AnalyticalPlan, PlanStep,
)
from datapilot.application.services.governed_analytical_binding import (
    bind_governed_analytical_plan,
)


class Provider:
    async def get_data_source_id(self, name):
        return 7 if name == "sales" else None

    async def list_semantic_entities(self, source_id):
        return [
            {"id": 1, "name": "Customer", "schema_name": "Sales",
             "table_name": "Customer", "attributes": [
                 {"name": "Region", "column_name": "RegionCode"},
                 {"name": "Segment", "column_name": "SegmentCode"},
             ]},
            {"id": 2, "name": "Supplier", "schema_name": "Purchasing",
             "table_name": "Supplier", "attributes": [
                 {"name": "Region", "column_name": "RegionCode"},
             ]},
        ]

    async def list_semantic_metrics(self, source_id):
        return [{"id": 3, "name": "Revenue"}, {"id": 4, "name": "Draft Revenue"}]

    async def list_time_dimensions(self, source_id):
        return [{"id": 5, "name": "Order Date"}]


class PublicationStore:
    def __init__(self, grants):
        self.grants = grants

    async def is_published(self, source_id, kind, semantic_id):
        return (source_id, kind, semantic_id) in self.grants


class AttributeStore:
    def __init__(self, grants):
        self.grants = grants

    async def is_published(self, source_id, entity_id, attribute_name):
        return (source_id, entity_id, attribute_name) in self.grants


def plan(dimension="Customer.Region", metric="Revenue"):
    return AnalyticalPlan(
        sources=("sales",),
        steps=(
            PlanStep(id="group", operation=AnalyticalOperation.GROUP,
                     inputs=("sales",), parameters={"dimension": dimension}),
            PlanStep(id="aggregate", operation=AnalyticalOperation.AGGREGATE,
                     inputs=("group",), parameters={"metric": metric}),
        ),
        output="aggregate",
    )


async def bind(*, dimension="Customer.Region", metric="Revenue", attrs=None, grants=None):
    return await bind_governed_analytical_plan(
        plan=plan(dimension, metric), datasource="sales",
        provider=Provider(),
        publication_store=PublicationStore(
            {(7, "metric", 3)} if grants is None else grants,
        ),
        attribute_publication_store=AttributeStore(
            {(7, 1, "Region")} if attrs is None else attrs,
        ),
    )


@pytest.mark.asyncio
async def test_published_attribute_and_metric_bind():
    bound = await bind()
    assert [(r.kind, r.name) for r in bound.references] == [
        ("dimension", "Customer.Region"), ("metric", "Revenue"),
    ]


@pytest.mark.asyncio
async def test_unique_unqualified_attribute_binds():
    bound = await bind(dimension="Region")
    assert bound.references[0].name == "Region"


@pytest.mark.asyncio
async def test_unpublished_attribute_is_rejected():
    with pytest.raises(ValueError, match="Unresolved"):
        await bind(attrs=set())


@pytest.mark.asyncio
async def test_entity_grant_does_not_approve_attribute():
    with pytest.raises(ValueError, match="Unresolved"):
        await bind(attrs=set(), grants={(7, "metric", 3), (7, "dimension", 1)})


@pytest.mark.asyncio
async def test_unpublished_metric_is_rejected():
    with pytest.raises(ValueError, match="Unresolved"):
        await bind(grants=set())


@pytest.mark.asyncio
async def test_ambiguous_unqualified_attribute_is_rejected():
    with pytest.raises(ValueError, match="Unresolved"):
        await bind(dimension="Region", attrs={(7, 1, "Region"), (7, 2, "Region")})


@pytest.mark.asyncio
async def test_qualified_attribute_resolves_with_ambiguous_short_name():
    bound = await bind(attrs={(7, 1, "Region"), (7, 2, "Region")})
    assert bound.references[0].name == "Customer.Region"


@pytest.mark.asyncio
async def test_draft_metric_is_not_bindable():
    with pytest.raises(ValueError, match="Unresolved"):
        await bind(metric="Draft Revenue")


@pytest.mark.asyncio
async def test_different_published_attribute_is_not_implicitly_available():
    with pytest.raises(ValueError, match="Unresolved"):
        await bind(dimension="Customer.Segment")
