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


def test_comparison_contract_violation_is_eligible_for_one_bounded_regeneration():
    from datapilot.application.services.sql_correction import classify_sql_correction
    decision = classify_sql_correction(correctness_checks=[{
        "code": "comparison_contract_violation",
        "status": "failed",
        "severity": "error",
        "missing_columns": ["status"],
    }])
    assert decision.recoverable is True
    assert decision.feedback[0]["missing_columns"] == ["status"]


def test_unverifiable_comparison_cannot_bypass_fail_closed_policy():
    from datapilot.application.services.sql_correction import classify_sql_correction
    decision = classify_sql_correction(correctness_checks=[
        {"code": "comparison_contract_violation", "status": "failed"},
        {"code": "filter_verification_unavailable", "status": "skipped"},
    ])
    assert decision.recoverable is False


@pytest.mark.parametrize("extra", [
    "AND status = 'A'",
    "AND status IN ('A')",
    "AND status != 'B'",
    "AND 'B' = status",
])
def test_extra_predicate_cannot_eliminate_required_cohort(extra):
    sql = (
        "SELECT status, COUNT(*) FROM public.items "
        "WHERE status IN ('A', 'B') " + extra + " GROUP BY status"
    )
    checks = assess_query_correctness(
        affected_tables=["public.items"], governed_tables=["public.items"],
        sql=sql,
        comparison_cohorts=[{"column_name": "status", "values": ["A", "B"]}],
        aggregation_grain=["status"],
    )
    assert any(c["code"] == "comparison_contract_violation" for c in checks)


@pytest.mark.parametrize("sql,expected", [
    ("SELECT region, COUNT(*) FROM public.items GROUP BY region", "passed"),
    ("SELECT COUNT(*) FROM public.items", "failed"),
    ("SELECT category, COUNT(*) FROM public.items GROUP BY category", "failed"),
])
def test_explicit_aggregation_grain_without_comparison_cohorts(sql, expected):
    checks = assess_query_correctness(
        affected_tables=["public.items"],
        governed_tables=["public.items"],
        sql=sql,
        aggregation_grain=["region"],
    )
    matches = [c for c in checks if c["code"].startswith("comparison_contract_")]
    assert len(matches) == 1
    assert matches[0]["status"] == expected
