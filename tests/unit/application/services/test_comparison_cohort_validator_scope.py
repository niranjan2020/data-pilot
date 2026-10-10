"""Comparison cohort grouping validator must use guaranteed predicates."""
import pytest
from datapilot.application.services.query_correctness import assess_query_correctness


def _checks(sql):
    return [c for c in assess_query_correctness(
        affected_tables=["public.items"],
        governed_tables=["public.items"],
        sql=sql,
        question="Compare status O versus status T",
    ) if c["code"] in {"comparison_dimension_violation", "comparison_dimension_alignment"}]


@pytest.mark.parametrize("sql", [
    "SELECT status, COUNT(*) FROM public.items WHERE status IN ('O','T') GROUP BY status",
    "SELECT region, status, COUNT(*) FROM public.items WHERE active = TRUE AND status IN ('O','T') GROUP BY region, status",
])
def test_grouped_cohorts_align(sql):
    assert any(c["status"] == "passed" for c in _checks(sql))


@pytest.mark.parametrize("sql", [
    "SELECT region, COUNT(*) FROM public.items WHERE status IN ('O','T') GROUP BY region",
    "SELECT COUNT(*) FROM public.items WHERE status IN ('O','T') GROUP BY region",
])
def test_ungrouped_cohorts_are_rejected(sql):
    assert any(c["status"] == "failed" for c in _checks(sql))


@pytest.mark.parametrize("sql", [
    "SELECT region, COUNT(*) FROM public.items WHERE status IN ('O','T') OR active = TRUE GROUP BY region",
    "SELECT region, COUNT(*) FROM public.items WHERE NOT (status IN ('O','T')) GROUP BY region",
    "SELECT region, COUNT(*) FROM public.items WHERE active = TRUE AND (status IN ('O','T') OR region = 'N') GROUP BY region",
])
def test_unguaranteed_in_is_not_treated_as_valid_cohort_evidence(sql):
    assert _checks(sql) == []
