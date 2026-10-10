"""Regression coverage for SQL array expansion and comparison grain.

These tests use generic physical tables and no domain-specific categories.
"""
import pytest

from datapilot.application.services.query_correctness import assess_query_correctness


def _checks(sql: str):
    return assess_query_correctness(
        affected_tables=["public.items"],
        governed_tables=["public.items"],
        sql=sql,
    )


@pytest.mark.parametrize("sql", [
    "SELECT UNNEST(tags), COUNT(*) FROM public.items GROUP BY UNNEST(tags)",
    "SELECT category, UNNEST(tags), COUNT(*) FROM public.items GROUP BY category, UNNEST(tags)",
])
def test_unnest_inside_group_by_is_rejected(sql):
    assert any(
        check["code"] == "array_expansion_grouping_violation"
        and check["status"] == "failed"
        for check in _checks(sql)
    )


def test_lateral_array_expansion_grouped_by_alias_is_not_rejected():
    sql = (
        "SELECT expanded.tag, COUNT(*) FROM public.items i "
        "CROSS JOIN LATERAL UNNEST(i.tags) AS expanded(tag) "
        "GROUP BY expanded.tag"
    )
    assert not any(
        check["code"] == "array_expansion_grouping_violation"
        for check in _checks(sql)
    )


def test_conditional_comparison_must_not_split_discriminator_grain():
    sql = (
        "SELECT category, "
        "SUM(CASE WHEN status = 'A' THEN amount ELSE 0 END) AS a, "
        "SUM(CASE WHEN status = 'B' THEN amount ELSE 0 END) AS b "
        "FROM public.items GROUP BY category, status"
    )
    assert any(
        check["code"] == "conditional_comparison_grain_violation"
        and check["status"] == "failed"
        for check in _checks(sql)
    )


def test_conditional_comparison_at_requested_grain_is_allowed():
    sql = (
        "SELECT category, "
        "SUM(CASE WHEN status = 'A' THEN amount ELSE 0 END) AS a, "
        "SUM(CASE WHEN status = 'B' THEN amount ELSE 0 END) AS b "
        "FROM public.items GROUP BY category"
    )
    assert not any(
        check["code"] == "conditional_comparison_grain_violation"
        for check in _checks(sql)
    )
