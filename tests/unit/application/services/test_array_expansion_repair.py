"""Cross-domain regression tests for conservative array expansion repair."""
import pytest
from sqlglot import parse_one
from datapilot.application.services.array_expansion_repair import repair_grouped_array_expansion
from datapilot.application.services.query_correctness import assess_query_correctness

FAILED = [{"code": "array_expansion_grouping_violation", "status": "failed"}]


@pytest.mark.parametrize("table,column", [
    ("public.products", "tags"),
    ("public.vessels", "alternative_fuel_type"),
    ("inventory.items", "categories"),
    ("analytics.events", "labels"),
])
def test_grouped_unnest_repair_expands_before_aggregation(table, column):
    sql = f"SELECT UNNEST({column}) AS category, COUNT(*) AS n FROM {table} GROUP BY UNNEST({column})"
    repaired = repair_grouped_array_expansion(sql, FAILED)
    assert repaired is not None
    assert "LATERAL" in repaired.upper()
    parsed = parse_one(repaired, read="postgres")
    assert parsed is not None
    checks = assess_query_correctness(
        sql=repaired, affected_tables=[table], governed_tables=[table],
    )
    assert not any(c.get("code") == "array_expansion_grouping_violation" and c.get("status") == "failed" for c in checks)


@pytest.mark.parametrize("sql", [
    "SELECT UNNEST(tags), COUNT(*) FROM public.products JOIN public.orders USING (id) GROUP BY UNNEST(tags)",
    "SELECT UNNEST(tags), COUNT(*) FROM public.products GROUP BY UNNEST(tags), UNNEST(labels)",
    "SELECT UNNEST(tags), COUNT(*) FROM public.products GROUP BY UNNEST(labels)",
    "SELECT UNNEST(tags), COUNT(*) FROM public.products WHERE EXISTS (SELECT 1 FROM public.orders) GROUP BY UNNEST(tags)",
])
def test_grouped_unnest_repair_fails_closed_for_unsafe_shapes(sql):
    assert repair_grouped_array_expansion(sql, FAILED) is None


def test_grouped_unnest_repair_requires_single_exclusive_failure():
    sql = "SELECT UNNEST(tags), COUNT(*) FROM public.products GROUP BY UNNEST(tags)"
    assert repair_grouped_array_expansion(sql, FAILED + [{"code": "comparison_dimension_violation", "status": "failed"}]) is None
