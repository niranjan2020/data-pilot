"""Batch regression matrix for governed categorical array filters and cohort grain."""
import pytest

from datapilot.application.services.query_correctness import assess_query_correctness


def _assess(sql, *, required_filters=(), question=""):
    return assess_query_correctness(
        affected_tables=["public.items"],
        governed_tables=["public.items"],
        sql=sql,
        question=question,
        required_filters=required_filters,
    )


@pytest.mark.parametrize("sql", [
    "SELECT * FROM public.items WHERE tags @> ARRAY['LNG']",
    "SELECT * FROM public.items WHERE 'LNG' = ANY(tags)",
    "SELECT * FROM public.items WHERE tags && ARRAY['LNG']",
])
def test_governed_array_membership_forms(sql):
    checks = _assess(sql, required_filters=[
        {"column_name": "tags", "operator": "=", "value": "LNG", "data_type": "text[]"}
    ])
    assert any(c["code"] == "filter_alignment" for c in checks)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM public.items WHERE name = 'LNG'",
    "SELECT * FROM public.items WHERE tags @> ARRAY['OTHER']",
    "SELECT * FROM public.items WHERE 'OTHER' = ANY(tags)",
    "SELECT * FROM public.items WHERE tags && ARRAY['OTHER']",
])
def test_wrong_array_value_or_column_is_not_alignment(sql):
    checks = _assess(sql, required_filters=[
        {"column_name": "tags", "operator": "=", "value": "LNG", "data_type": "text[]"}
    ])
    assert any(c["code"] == "filter_violation" for c in checks)


@pytest.mark.parametrize("sql,expected", [
    (
        "SELECT category, COUNT(*) FROM public.items WHERE status IN ('A','B') GROUP BY category",
        "comparison_dimension_violation",
    ),
    (
        "SELECT category, status, COUNT(*) FROM public.items WHERE status IN ('A','B') GROUP BY category,status",
        "comparison_dimension_alignment",
    ),
])
def test_explicit_comparison_cohort_separation(sql, expected):
    checks = _assess(sql, question="Compare status A versus B by category")
    assert any(c["code"] == expected for c in checks)


def test_combined_cohort_is_not_forced_into_separate_grain():
    checks = _assess(
        "SELECT category, COUNT(*) FROM public.items WHERE status IN ('A','B') GROUP BY category",
        question="Show status A and B combined by category",
    )
    assert not any(c["code"] == "comparison_dimension_violation" for c in checks)
