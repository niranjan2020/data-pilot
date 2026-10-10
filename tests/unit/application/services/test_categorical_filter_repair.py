"""Batch coverage for safe deterministic canonical filter repair."""
import pytest

from datapilot.application.services.query_orchestrator import QueryOrchestrator
from datapilot.application.services.query_correctness import assess_query_correctness


def _repair(sql, column="status", value="O"):
    checks = [{
        "code": "filter_violation", "status": "failed",
        "column": column, "operator": "=", "expected_value": value,
    }]
    return QueryOrchestrator._repair_missing_governed_filter(sql, checks)


def test_missing_filter_is_added_to_simple_grouping_query():
    sql = "SELECT status, COUNT(*) FROM public.items GROUP BY status"
    repaired = _repair(sql)
    assert repaired is not None
    checks = assess_query_correctness(
        affected_tables=["public.items"], governed_tables=["public.items"],
        sql=repaired,
        required_filters=[{"column_name": "status", "operator": "=", "value": "O"}],
    )
    assert any(c["code"] == "filter_alignment" for c in checks)


def test_existing_unrelated_where_is_preserved():
    sql = "SELECT status, COUNT(*) FROM public.items WHERE active = TRUE GROUP BY status"
    repaired = _repair(sql)
    assert repaired is not None
    assert "active = TRUE" in repaired


@pytest.mark.parametrize("sql", [
    "SELECT status, COUNT(*) FROM public.items WHERE status = 'T' GROUP BY status",
    "SELECT status, COUNT(*) FROM public.items WHERE status IN ('T') GROUP BY status",
    "SELECT i.status, COUNT(*) FROM public.items i JOIN public.other o ON i.id = o.id GROUP BY i.status",
    "SELECT COUNT(*) FROM public.items",
    "SELECT status FROM public.items WHERE status = 'O' OR active = TRUE",
])
def test_unsafe_or_existing_filter_is_not_rewritten(sql):
    assert _repair(sql) is None


def test_multiple_missing_filters_are_not_repaired():
    checks = [
        {"code": "filter_violation", "column": "status", "operator": "=", "expected_value": "O"},
        {"code": "filter_violation", "column": "region", "operator": "=", "expected_value": "N"},
    ]
    assert QueryOrchestrator._repair_missing_governed_filter(
        "SELECT status, region FROM public.items", checks,
    ) is None
