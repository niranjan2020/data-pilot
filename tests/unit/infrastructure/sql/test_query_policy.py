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
        QueryExecutionPolicy(default_limit=100, max_limit=100),
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


def test_does_not_add_limit_to_scalar_aggregate_query() -> None:
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


def test_adds_limit_to_grouped_aggregate_query() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT customer_id, COUNT(*) AS order_count FROM orders GROUP BY customer_id",
        "postgres",
        QueryExecutionPolicy(default_limit=100),
    )

    assert result.is_allowed
    assert "LIMIT 100" in result.sql.upper()
    assert result.warnings


def test_result_limit_never_exceeds_max_result_rows() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT id FROM customers",
        "postgres",
        QueryExecutionPolicy(
            default_limit=250,
            max_limit=250,
            max_result_rows=250,
        ),
    )

    assert result.is_allowed
    assert "LIMIT 250" in result.sql.upper()


def test_adds_limit_to_distinct_query() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT DISTINCT country FROM customers",
        "postgres",
        QueryExecutionPolicy(default_limit=100),
    )

    assert result.is_allowed
    assert "LIMIT 100" in result.sql.upper()


def test_adds_limit_to_set_operation() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT id FROM active_customers UNION SELECT id FROM archived_customers",
        "postgres",
        QueryExecutionPolicy(default_limit=100),
    )

    assert result.is_allowed
    assert "LIMIT 100" in result.sql.upper()


def test_rejects_parameterized_limit() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT id FROM customers LIMIT $1",
        "postgres",
        QueryExecutionPolicy(),
    )

    assert not result.is_allowed
    assert any("LIMIT must be" in error for error in result.errors)


def test_rejects_expression_limit() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT id FROM customers LIMIT 10 + 5",
        "postgres",
        QueryExecutionPolicy(),
    )

    assert not result.is_allowed
    assert any("LIMIT must be" in error for error in result.errors)


def test_zero_limit_is_deterministically_allowed() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT id FROM customers LIMIT 0",
        "postgres",
        QueryExecutionPolicy(),
    )

    assert result.is_allowed
    assert "LIMIT 0" in result.sql.upper()


def test_scalar_aggregate_with_alias_remains_unlimited() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT COUNT(*) AS customer_count, MAX(id) AS max_id FROM customers",
        "postgres",
        QueryExecutionPolicy(default_limit=100),
    )

    assert result.is_allowed
    assert "LIMIT" not in result.sql.upper()


def test_mixed_aggregate_projection_is_bounded_fail_safe() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT customer_id, COUNT(*) FROM orders",
        "postgres",
        QueryExecutionPolicy(default_limit=100),
    )

    assert result.is_allowed
    assert "LIMIT 100" in result.sql.upper()


def test_explicit_limit_is_capped_by_effective_result_budget() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT id FROM customers LIMIT 500",
        "postgres",
        QueryExecutionPolicy(default_limit=50, max_limit=50, max_result_rows=50),
    )

    assert result.is_allowed
    assert "LIMIT 50" in result.sql.upper()


def test_window_aggregate_is_bounded_as_row_producing() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT employee_id, SUM(salary) OVER (PARTITION BY department_id) AS department_total FROM employees",
        "postgres",
        QueryExecutionPolicy(default_limit=100),
    )

    assert result.is_allowed
    assert "LIMIT 100" in result.sql.upper()


def test_window_aggregate_only_projection_is_still_bounded() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT SUM(salary) OVER () FROM employees",
        "postgres",
        QueryExecutionPolicy(default_limit=100),
    )

    assert result.is_allowed
    assert "LIMIT 100" in result.sql.upper()


def test_nested_aggregate_subquery_is_bounded_by_outer_cardinality() -> None:
    result = SQLQueryPolicyEnforcer().enforce(
        "SELECT (SELECT MAX(price) FROM products WHERE products.category_id = categories.id) AS max_price FROM categories",
        "postgres",
        QueryExecutionPolicy(default_limit=100),
    )

    assert result.is_allowed
    assert "LIMIT 100" in result.sql.upper()
