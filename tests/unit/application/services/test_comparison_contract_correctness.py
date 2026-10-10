"""SQL must preserve cohorts supplied by trusted semantic metadata."""
import pytest
from datapilot.application.services.query_correctness import assess_query_correctness


@pytest.mark.parametrize("sql,expected", [
    ("SELECT status, COUNT(*) FROM public.items WHERE status IN ('A', 'B') GROUP BY status", "passed"),
    ("SELECT COUNT(*) FROM public.items WHERE status IN ('A', 'B')", "failed"),
    ("SELECT status, COUNT(*) FROM public.items GROUP BY status", "failed"),
    ("SELECT status, COUNT(*) FROM public.items WHERE status IN ('A') GROUP BY status", "failed"),
    ("SELECT status, COUNT(*) FROM public.items WHERE status IN ('A', 'B') OR active = TRUE GROUP BY status", "failed"),
    ("SELECT status, COUNT(*) FROM public.items WHERE status IN ('A', 'B') AND active = TRUE GROUP BY status", "passed"),
    ("SELECT status, region, COUNT(*) FROM public.items WHERE status IN ('A', 'B') GROUP BY status, region", "passed"),
])
def test_comparison_contract(sql, expected):
    checks = assess_query_correctness(
        affected_tables=["public.items"],
        governed_tables=["public.items"],
        sql=sql,
        comparison_cohorts=[{"column_name": "status", "values": ["A", "B"]}],
        aggregation_grain=["status"],
    )
    matches = [c for c in checks if c["code"].startswith("comparison_contract_")]
    assert len(matches) == 1
    assert matches[0]["status"] == expected


def test_contract_uses_exact_canonical_values_not_substrings():
    checks = assess_query_correctness(
        affected_tables=["public.items"],
        governed_tables=["public.items"],
        sql="SELECT status, COUNT(*) FROM public.items WHERE status IN ('A', 'BC') GROUP BY status",
        comparison_cohorts=[{"column_name": "status", "values": ["A", "B"]}],
        aggregation_grain=["status"],
    )
    assert any(c["code"] == "comparison_contract_violation" for c in checks)
