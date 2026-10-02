"""Tests for query resource policy enforcement."""

from datapilot.domain.policies import QueryExecutionPolicy
from datapilot.infrastructure.sql.query_policy import SQLQueryPolicyEnforcer


def test_adds_default_limit_to_non_aggregate_select() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT id, name FROM customers",
        "postgres",
        QueryExecutionPolicy(default_limit=100),
    )

    assert result.is_allowed
    assert "LIMIT 100" in result.sql.upper()
    assert result.warnings


def test_preserves_explicit_limit_within_policy() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT id FROM customers LIMIT 50",
        "postgres",
        QueryExecutionPolicy(max_limit=100),
    )

    assert result.is_allowed
    assert "LIMIT 50" in result.sql.upper()


def test_reduces_excessive_limit() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT id FROM customers LIMIT 5000",
        "postgres",
        QueryExecutionPolicy(max_limit=1000),
    )

    assert result.is_allowed
    assert "LIMIT 1000" in result.sql.upper()


def test_does_not_add_limit_to_aggregate_query() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT COUNT(*) FROM customers",
        "postgres",
        QueryExecutionPolicy(),
    )

    assert result.is_allowed
    assert "LIMIT" not in result.sql.upper()


def test_rejects_overlong_query() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT " + "x" * 100,
        "postgres",
        QueryExecutionPolicy(max_query_length=50),
    )

    assert not result.is_allowed
    assert result.errors
