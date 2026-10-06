"""Tests for fail-closed provider-neutral execution recovery policy."""

from datapilot.application.services.execution_recovery import classify_execution_error
from datapilot.domain.execution_recovery import ExecutionRecoveryEvidence


def test_provider_recoverable_evidence_is_accepted():
    decision = classify_execution_error(
        evidence=ExecutionRecoveryEvidence(
            recoverable=True,
            category="sql_execution",
            reason="provider says SQL can be corrected",
            provider="example",
            code="E_COLUMN",
        )
    )
    assert decision.recoverable is True
    assert decision.category == "sql_execution"
    assert decision.provider == "example"
    assert decision.code == "E_COLUMN"


def test_provider_terminal_evidence_remains_terminal():
    decision = classify_execution_error(
        evidence=ExecutionRecoveryEvidence(
            recoverable=False,
            category="provider_runtime",
            reason="provider runtime failure",
            provider="example",
            code="E_TIMEOUT",
        )
    )
    assert decision.recoverable is False
    assert decision.category == "provider_runtime"


def test_missing_provider_classification_fails_closed():
    decision = classify_execution_error()
    assert decision.recoverable is False
    assert decision.category == "unknown"
    assert decision.code is None


def test_application_policy_does_not_interpret_vendor_code():
    decision = classify_execution_error(
        evidence=ExecutionRecoveryEvidence(
            recoverable=False,
            category="unknown",
            reason="unknown provider code",
            provider="mysql",
            code="42703",
        )
    )
    assert decision.recoverable is False
    assert decision.code == "42703"
