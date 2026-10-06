"""Tests for deterministic database execution-error recovery classification."""

import pytest

from datapilot.application.services.execution_recovery import classify_execution_error


@pytest.mark.parametrize("sqlstate", ["42601", "42703", "42P01", "42883", "42804", "42803"])
def test_sql_shape_execution_errors_are_recoverable(sqlstate):
    decision = classify_execution_error(details={"sqlstate": sqlstate})
    assert decision.recoverable is True
    assert decision.category == "sql_execution"
    assert decision.sqlstate == sqlstate


@pytest.mark.parametrize(
    "sqlstate",
    ["42501", "28000", "28P01", "57014", "53300", "53400", "57P01", "08006"],
)
def test_runtime_auth_resource_and_connection_errors_are_terminal(sqlstate):
    decision = classify_execution_error(details={"sqlstate": sqlstate})
    assert decision.recoverable is False
    assert decision.category == "provider_runtime"
    assert decision.sqlstate == sqlstate


def test_unknown_execution_error_code_fails_closed():
    decision = classify_execution_error(details={"sqlstate": "XX999"})
    assert decision.recoverable is False
    assert decision.category == "unknown"


def test_missing_structured_error_code_fails_closed_even_with_sql_like_message():
    decision = classify_execution_error(
        details={"message": 'column "missing" does not exist'}
    )
    assert decision.recoverable is False
    assert decision.category == "unknown"
    assert decision.sqlstate is None


@pytest.mark.parametrize("key", ["sql_state", "pgcode", "code"])
def test_common_provider_code_fields_are_normalized(key):
    decision = classify_execution_error(details={key: "42703"})
    assert decision.recoverable is True
    assert decision.sqlstate == "42703"


def test_privilege_error_overrides_recoverable_sqlstate_class():
    decision = classify_execution_error(details={"sqlstate": "42501"})
    assert decision.recoverable is False
