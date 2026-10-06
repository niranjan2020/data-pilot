"""Tests for coherent query execution resource budgets."""

import pytest
from pydantic import ValidationError

from datapilot.domain.policies import QueryExecutionPolicy


def test_default_resource_budget_is_coherent() -> None:
    policy = QueryExecutionPolicy()

    assert policy.resource_budget() == {
        "timeout_seconds": 30.0,
        "max_result_rows": 1000,
        "max_query_length": 100000,
        "require_limit_for_non_aggregate": True,
        "default_limit": 1000,
        "max_limit": 1000,
    }


def test_rejects_default_limit_above_max_limit() -> None:
    with pytest.raises(ValidationError, match="default_limit must be less than or equal to max_limit"):
        QueryExecutionPolicy(default_limit=501, max_limit=500)


def test_rejects_max_limit_above_max_result_rows() -> None:
    with pytest.raises(ValidationError, match="max_limit must be less than or equal to max_result_rows"):
        QueryExecutionPolicy(max_limit=1000, max_result_rows=500)


def test_accepts_tighter_coherent_resource_budget() -> None:
    policy = QueryExecutionPolicy(
        timeout_seconds=12.5,
        max_result_rows=500,
        default_limit=100,
        max_limit=500,
    )

    assert policy.resource_budget()["timeout_seconds"] == 12.5
    assert policy.resource_budget()["max_result_rows"] == 500
