"""Conditional comparison measures must preserve independent cohort outputs."""
import pytest
from datapilot.application.services.query_correctness import assess_query_correctness

BASE = " FROM public.items WHERE status IN ('O', 'T') GROUP BY region"


def status(sql, question="Compare status O versus status T"):
    checks = assess_query_correctness(
        affected_tables=["public.items"], governed_tables=["public.items"],
        sql=sql, question=question,
    )
    matching = [c for c in checks if c["code"] in (
        "comparison_dimension_alignment", "comparison_dimension_violation",
    )]
    assert len(matching) == 1
    return matching[0]["status"]


@pytest.mark.parametrize("measures", [
    "SUM(CASE WHEN status = 'O' THEN 1 ELSE 0 END), SUM(CASE WHEN status = 'T' THEN 1 ELSE 0 END)",
    "COUNT(*) FILTER (WHERE status = 'O'), COUNT(*) FILTER (WHERE status = 'T')",
    "SUM(CASE WHEN 'O' = status THEN amount ELSE 0 END), SUM(CASE WHEN 'T' = status THEN amount ELSE 0 END)",
    "SUM(CASE WHEN status = 'O' THEN amount ELSE 0 END), COUNT(*) FILTER (WHERE status = 'T')",
    "COUNT(*) FILTER (WHERE status = 'T'), COUNT(*) FILTER (WHERE status = 'O')",
    "SUM(CASE WHEN status = 'O' THEN 1 ELSE 0 END), SUM(CASE WHEN status = 'T' THEN 1 ELSE 0 END), COUNT(*)",
])
def test_independent_cohort_measures_pass(measures):
    assert status("SELECT region, " + measures + BASE) == "passed"


@pytest.mark.parametrize("measures", [
    "SUM(CASE WHEN status = 'O' THEN 1 WHEN status = 'T' THEN 1 ELSE 0 END)",
    "SUM(CASE WHEN status = 'O' THEN amount WHEN status = 'T' THEN amount ELSE 0 END)",
    "COUNT(*) FILTER (WHERE status = 'O' OR status = 'T')",
    "SUM(CASE WHEN status IN ('O','T') THEN 1 ELSE 0 END)",
    "COUNT(*) FILTER (WHERE status = 'O'), COUNT(*) FILTER (WHERE status = 'O')",
    "SUM(CASE WHEN status = 'O' THEN 1 ELSE 0 END), COUNT(*)",
    "SUM(CASE WHEN status = 'O' OR active THEN 1 ELSE 0 END), SUM(CASE WHEN status = 'T' THEN 1 ELSE 0 END)",
    "SUM(CASE WHEN status = 'O' THEN 1 WHEN status = 'O' THEN 2 ELSE 0 END), SUM(CASE WHEN status = 'T' THEN 1 ELSE 0 END)",
    "SUM(CASE WHEN status = 'O' THEN 1 WHEN status = 'T' THEN 2 ELSE 0 END), SUM(CASE WHEN status = 'T' THEN 1 ELSE 0 END)",
    "COUNT(*) FILTER (WHERE status = 'X'), COUNT(*) FILTER (WHERE status = 'T')",
])
def test_collapsed_or_unreliable_measures_fail(measures):
    assert status("SELECT region, " + measures + BASE) == "failed"


@pytest.mark.parametrize("question", [
    "Compare status O versus status T",
    "Comparison of status O and status T",
    "Show status O vs status T",
])
def test_comparison_phrasing_preserves_independent_cohorts(question):
    sql = ("SELECT region, COUNT(*) FILTER (WHERE status = 'O'), "
           "COUNT(*) FILTER (WHERE status = 'T')" + BASE)
    assert status(sql, question) == "passed"
