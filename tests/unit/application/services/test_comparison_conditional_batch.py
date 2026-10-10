"""Batch: conditional cohort validation against published SQL cohort literals."""
import pytest
from datapilot.application.services.query_correctness import assess_query_correctness


def _comparison(sql, question="Compare status O versus status T"):
    checks = assess_query_correctness(
        affected_tables=["public.items"], governed_tables=["public.items"],
        sql=sql, question=question,
    )
    return next((c for c in checks if c["code"] in {
        "comparison_dimension_alignment", "comparison_dimension_violation",
    }), None)


BASE = " FROM public.items WHERE status IN ('O', 'T') GROUP BY region"


@pytest.mark.parametrize("sql", [
    "SELECT region, SUM(CASE WHEN status = 'O' THEN 1 ELSE 0 END) AS owned, SUM(CASE WHEN status = 'T' THEN 1 ELSE 0 END) AS chartered" + BASE,
    "SELECT region, COUNT(*) FILTER (WHERE status = 'O') AS owned, COUNT(*) FILTER (WHERE status = 'T') AS chartered" + BASE,
])
def test_two_conditional_cohorts_preserve_comparison(sql):
    assert _comparison(sql)["status"] == "passed"


@pytest.mark.parametrize("sql", [
    "SELECT region, COUNT(*)" + BASE,
    "SELECT region, SUM(CASE WHEN status = 'O' THEN 1 ELSE 0 END)" + BASE,
    "SELECT region, SUM(CASE WHEN status = 'O' THEN 1 ELSE 0 END), SUM(CASE WHEN status = 'X' THEN 1 ELSE 0 END)" + BASE,
    "SELECT region, SUM(CASE WHEN status = 'O' OR active = TRUE THEN 1 ELSE 0 END), SUM(CASE WHEN status = 'T' THEN 1 ELSE 0 END)" + BASE,
    "SELECT region, SUM(CASE WHEN status <> 'O' THEN 1 ELSE 0 END), SUM(CASE WHEN status = 'T' THEN 1 ELSE 0 END)" + BASE,
])
def test_collapsed_or_unsafe_conditional_cohorts_fail(sql):
    assert _comparison(sql)["status"] == "failed"


@pytest.mark.parametrize("sql", [
    "SELECT region, status, COUNT(*) FROM public.items WHERE status IN ('O','T') GROUP BY region, status",
    "SELECT region, status, SUM(amount) FROM public.items WHERE status IN ('O','T') GROUP BY region, status",
])
def test_explicit_grouping_preserves_cohorts(sql):
    assert _comparison(sql)["status"] == "passed"


def test_combined_total_is_not_forced_into_comparison():
    sql = "SELECT region, COUNT(*) FROM public.items WHERE status IN ('O','T') GROUP BY region"
    assert _comparison(sql, "Show combined total for O and T") is None
