import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from datapilot.application.services.semantic_context import SemanticContextAssembler
from datapilot.application.services.time_semantics import resolve_time_semantics
from datapilot.application.services.query_correctness import assess_query_correctness


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


@pytest.mark.asyncio
async def test_versioned_metadata_fixture_selects_default_order_date_for_temporal_revenue():
    assembler = SemanticContextAssembler(FixtureMetadataProvider())

    context = await assembler.assemble(
        "Generic Commerce",
        [
            {"kind": "entity", "name": "Order", "metadata": {"id": 203}},
            {"kind": "metric", "name": "Revenue", "metadata": {"id": 401}},
        ],
        "Show revenue last month",
    )

    assert {entity["name"] for entity in context["entities"]} == {"Order"}
    assert {metric["name"] for metric in context["metrics"]} == {"Revenue"}
    assert [dimension["name"] for dimension in context["time_dimensions"]] == [
        "Order Date"
    ]
    time_dimension = context["time_dimensions"][0]
    assert time_dimension["column_name"] == "order_date"
    assert time_dimension["role"] == "order_date"
    assert time_dimension["is_default"] is True


@pytest.mark.asyncio
async def test_versioned_metadata_fixture_selects_order_date_for_monthly_revenue():
    assembler = SemanticContextAssembler(FixtureMetadataProvider())

    context = await assembler.assemble(
        "Generic Commerce",
        [
            {"kind": "entity", "name": "Order", "metadata": {"id": 203}},
            {"kind": "metric", "name": "Revenue", "metadata": {"id": 401}},
        ],
        "Show monthly revenue this year",
    )

    assert [dimension["name"] for dimension in context["time_dimensions"]] == [
        "Order Date"
    ]
    assert "month" in context["time_dimensions"][0]["supported_grains"]


@pytest.mark.asyncio
async def test_versioned_metadata_fixture_does_not_leak_order_time_into_product_only_query():
    assembler = SemanticContextAssembler(FixtureMetadataProvider())

    context = await assembler.assemble(
        "Generic Commerce",
        [{"kind": "entity", "name": "Product", "metadata": {"id": 202}}],
        "Show products",
    )

    assert {entity["name"] for entity in context["entities"]} == {"Product"}
    assert context["time_dimensions"] == []


A3_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=ZoneInfo("UTC"))


def _fixture_time_dimensions():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["time_dimensions"]


@pytest.mark.parametrize(
    ("question", "expected_start", "expected_end"),
    [
        ("Show revenue last month", "2026-09-01", "2026-10-01"),
        ("Show YTD revenue", "2026-01-01", "2026-10-06"),
        ("Show revenue for the last 30 days", "2026-09-06", "2026-10-06"),
    ],
)
def test_versioned_metadata_fixture_resolves_governed_time_ranges(
    question, expected_start, expected_end
):
    result = resolve_time_semantics(
        question,
        _fixture_time_dimensions(),
        now=A3_NOW,
    )

    assert result is not None
    assert result["status"] == "resolved"
    assert result["time_dimension"] == "Order Date"
    assert result["entity"] == "Order"
    assert result["schema_name"] == "public"
    assert result["table_name"] == "orders"
    assert result["column_name"] == "order_date"
    assert result["start"] == expected_start
    assert result["end_exclusive"] == expected_end
    assert result["comparison"] is False


@pytest.mark.parametrize(
    ("question", "expected_start", "expected_end", "expected_grain"),
    [
        (
            "Show monthly revenue this year",
            "2026-01-01",
            "2027-01-01",
            "month",
        ),
        (
            "Show revenue by month for the last 12 months",
            "2025-11-01",
            "2026-10-06",
            "month",
        ),
    ],
)
def test_versioned_metadata_fixture_resolves_governed_time_filter_and_grain(
    question, expected_start, expected_end, expected_grain
):
    result = resolve_time_semantics(
        question,
        _fixture_time_dimensions(),
        now=A3_NOW,
    )

    assert result is not None
    assert result["status"] == "resolved"
    assert result["time_dimension"] == "Order Date"
    assert result["column_name"] == "order_date"
    assert result["start"] == expected_start
    assert result["end_exclusive"] == expected_end
    assert result["grouping_grain"] == expected_grain
    assert result["comparison"] is False


def test_versioned_metadata_fixture_resolves_grouping_only_without_inventing_filter():
    result = resolve_time_semantics(
        "Show revenue by quarter",
        _fixture_time_dimensions(),
        now=A3_NOW,
    )

    assert result is not None
    assert result["status"] == "resolved"
    assert result["time_dimension"] == "Order Date"
    assert result["column_name"] == "order_date"
    assert result["grouping_grain"] == "quarter"
    assert result["filter"] is None
    assert "start" not in result
    assert "end_exclusive" not in result
    assert result["comparison"] is False


def test_versioned_metadata_fixture_resolves_month_over_month_comparison():
    result = resolve_time_semantics(
        "Compare revenue this month vs last month",
        _fixture_time_dimensions(),
        now=A3_NOW,
    )

    assert result is not None
    assert result["status"] == "resolved"
    assert result["time_dimension"] == "Order Date"
    assert result["column_name"] == "order_date"
    assert result["comparison"] is True
    assert result["periods"] == [
        {
            "label": "this month",
            "start": "2026-10-01",
            "end_exclusive": "2026-11-01",
        },
        {
            "label": "last month",
            "start": "2026-09-01",
            "end_exclusive": "2026-10-01",
        },
    ]


def test_versioned_metadata_fixture_resolves_year_over_year_comparison():
    result = resolve_time_semantics(
        "Compare revenue this year vs last year",
        _fixture_time_dimensions(),
        now=A3_NOW,
    )

    assert result is not None
    assert result["status"] == "resolved"
    assert result["time_dimension"] == "Order Date"
    assert result["column_name"] == "order_date"
    assert result["comparison"] is True
    assert result["periods"] == [
        {
            "label": "current period",
            "start": "2026-01-01",
            "end_exclusive": "2027-01-01",
        },
        {
            "label": "prior-year period",
            "start": "2025-01-01",
            "end_exclusive": "2026-01-01",
        },
    ]


def test_fixture_resolved_time_plan_aligns_with_generated_sql_correctness():
    plan = resolve_time_semantics(
        "Show monthly revenue this year",
        _fixture_time_dimensions(),
        now=A3_NOW,
    )

    checks = assess_query_correctness(
        affected_tables=["public.orders"],
        governed_tables=["public.orders"],
        sql="""SELECT DATE_TRUNC('month', order_date), SUM(amount)
               FROM public.orders
               WHERE order_date >= DATE '2026-01-01'
                 AND order_date < DATE '2027-01-01'
               GROUP BY DATE_TRUNC('month', order_date)""",
        required_time_plan=plan,
    )

    assert any(
        check["code"] == "time_filter_alignment" and check["status"] == "passed"
        for check in checks
    )
    assert any(
        check["code"] == "time_grain_alignment" and check["status"] == "passed"
        for check in checks
    )


def test_fixture_resolved_time_plan_rejects_wrong_column_boundary_and_grain():
    plan = resolve_time_semantics(
        "Show monthly revenue this year",
        _fixture_time_dimensions(),
        now=A3_NOW,
    )

    checks = assess_query_correctness(
        affected_tables=["public.orders"],
        governed_tables=["public.orders"],
        sql="""SELECT DATE_TRUNC('year', created_at), SUM(amount)
               FROM public.orders
               WHERE created_at >= DATE '2026-02-01'
                 AND created_at < DATE '2027-01-01'
               GROUP BY DATE_TRUNC('year', created_at)""",
        required_time_plan=plan,
    )

    filter_violation = next(
        check for check in checks if check["code"] == "time_filter_violation"
    )
    grain_violation = next(
        check for check in checks if check["code"] == "time_grain_violation"
    )
    assert filter_violation["status"] == "failed"
    assert filter_violation["missing_lower_bound"] is True
    assert grain_violation["status"] == "failed"


def test_fixture_resolved_grouping_only_plan_aligns_without_time_filter():
    plan = resolve_time_semantics(
        "Show revenue by quarter",
        _fixture_time_dimensions(),
        now=A3_NOW,
    )

    checks = assess_query_correctness(
        affected_tables=["public.orders"],
        governed_tables=["public.orders"],
        sql="""SELECT DATE_TRUNC('quarter', order_date), SUM(amount)
               FROM public.orders
               GROUP BY DATE_TRUNC('quarter', order_date)""",
        required_time_plan=plan,
    )

    assert any(
        check["code"] == "time_grain_alignment" and check["status"] == "passed"
        for check in checks
    )
    assert not any(check["code"] == "time_filter_violation" for check in checks)
