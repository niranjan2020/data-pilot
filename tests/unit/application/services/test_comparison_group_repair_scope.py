"""Comparison grain repair must not infer cohorts from OR or NOT branches."""
import pytest
from datapilot.application.services.comparison_group_repair import repair_missing_comparison_groups

CHECKS = [{"code": "comparison_dimension_violation", "status": "failed",
           "missing_columns": ["status"]}]


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) FROM items WHERE status IN ('O','T') GROUP BY region",
    "SELECT COUNT(*) FROM items WHERE active = TRUE AND status IN ('O','T') GROUP BY region",
])
def test_repair_safe_conjunctive_cohorts(sql):
    result = repair_missing_comparison_groups(sql, CHECKS)
    assert result is not None
    assert "status" in result.lower()


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) FROM items WHERE status IN ('O','T') OR active = TRUE GROUP BY region",
    "SELECT COUNT(*) FROM items WHERE NOT (status IN ('O','T')) GROUP BY region",
    "SELECT COUNT(*) FROM items WHERE active = TRUE AND (status IN ('O','T') OR region = 'N') GROUP BY region",
    "SELECT COUNT(*) FROM items WHERE status IN ('O','T') AND status IN ('T','TO') GROUP BY region",
])
def test_repair_rejects_non_guaranteed_or_ambiguous_cohorts(sql):
    assert repair_missing_comparison_groups(sql, CHECKS) is None
