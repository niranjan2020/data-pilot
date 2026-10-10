"""Detect SQL filters that eliminate cohorts after a valid IN clause."""
import pytest
from datapilot.application.services.query_correctness import assess_query_correctness


def verdict(sql):
    checks = assess_query_correctness(
        affected_tables=["public.items"], governed_tables=["public.items"],
        sql=sql, question="Compare status O versus status T",
    )
    matches = [c for c in checks if c["code"] in (
        "comparison_dimension_violation", "comparison_dimension_alignment"
    )]
    assert len(matches) == 1
    return matches[0]["status"]


PREFIX = "SELECT status, COUNT(*) FROM public.items WHERE status IN ('O','T')"
SUFFIX = " GROUP BY status"


@pytest.mark.parametrize("extra", [
    "status = 'O'",
    "status = 'T'",
    "status = 'X'",
    "status IN ('O')",
    "status IN ('T')",
    "status IN ('X')",
    "status IN ('O','X')",
    "status IN ('T','X')",
    "status <> 'O'",
    "status <> 'T'",
])
def test_extra_conjunct_cannot_remove_cohort(extra):
    assert verdict(PREFIX + " AND " + extra + SUFFIX) == "failed"


@pytest.mark.parametrize("extra", [
    "active = TRUE",
    "region = 'North'",
    "status IN ('O','T')",
    "status IN ('O','T','X')",
])
def test_nonrestrictive_conjunct_preserves_cohorts(extra):
    assert verdict(PREFIX + " AND " + extra + SUFFIX) == "passed"


def test_comparison_without_extra_conjunct_remains_valid():
    assert verdict(PREFIX + SUFFIX) == "passed"


def test_ungrouped_comparison_still_fails():
    assert verdict("SELECT region, COUNT(*) FROM public.items WHERE status IN ('O','T') GROUP BY region") == "failed"


@pytest.mark.parametrize("extra", [
    "NOT (status IN ('O'))",
    "NOT (status IN ('T'))",
    "NOT (status IN ('O','T'))",
])
def test_negated_cohort_predicates_are_rejected(extra):
    assert verdict(PREFIX + " AND " + extra + SUFFIX) == "failed"
