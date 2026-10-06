"""Deterministic policy for database execution-error recovery eligibility."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


# SQLSTATE classes/codes that indicate the submitted SQL itself is invalid and
# can potentially be regenerated from the same governed semantic context.
_RECOVERABLE_SQLSTATE_PREFIXES = ("42",)  # syntax/access-rule category
_RECOVERABLE_SQLSTATES = frozenset({
    "42703",  # undefined_column
    "42P01",  # undefined_table
    "42883",  # undefined_function
    "42804",  # datatype_mismatch
    "42803",  # grouping_error
    "42601",  # syntax_error
})

# Access/auth errors share SQLSTATE class 42 in PostgreSQL, but regenerating SQL
# cannot grant privileges. They must override the broad class-level rule.
_TERMINAL_SQLSTATES = frozenset({
    "42501",  # insufficient_privilege
    "28000",  # invalid_authorization_specification
    "28P01",  # invalid_password
    "57014",  # query_canceled / timeout
    "53300",  # too_many_connections
    "53400",  # configuration_limit_exceeded
    "57P01",  # admin_shutdown
    "57P02",  # crash_shutdown
    "57P03",  # cannot_connect_now
})


@dataclass(frozen=True)
class ExecutionRecoveryDecision:
    recoverable: bool
    category: str
    reason: str
    sqlstate: str | None = None


def classify_execution_error(
    *,
    details: Mapping[str, Any] | None = None,
) -> ExecutionRecoveryDecision:
    """Classify a database execution failure without performing a retry.

    Classification is intentionally evidence-based and fail-closed. A missing or
    unknown provider error code is terminal rather than guessed from message text.
    """
    payload = dict(details or {})
    raw_sqlstate = (
        payload.get("sqlstate")
        or payload.get("sql_state")
        or payload.get("pgcode")
        or payload.get("code")
    )
    sqlstate = str(raw_sqlstate).strip().upper() if raw_sqlstate else None

    if not sqlstate:
        return ExecutionRecoveryDecision(
            recoverable=False,
            category="unknown",
            reason="Execution failure has no structured provider error code.",
        )

    if sqlstate in _TERMINAL_SQLSTATES or sqlstate.startswith(("08", "28", "53", "57", "58")):
        return ExecutionRecoveryDecision(
            recoverable=False,
            category="provider_runtime",
            reason="Connection, authorization, cancellation, resource, or provider failures are terminal.",
            sqlstate=sqlstate,
        )

    if sqlstate in _RECOVERABLE_SQLSTATES or sqlstate.startswith(_RECOVERABLE_SQLSTATE_PREFIXES):
        return ExecutionRecoveryDecision(
            recoverable=True,
            category="sql_execution",
            reason="Structured provider code indicates a correctable SQL execution failure.",
            sqlstate=sqlstate,
        )

    return ExecutionRecoveryDecision(
        recoverable=False,
        category="unknown",
        reason="Provider error code is not explicitly eligible for SQL correction.",
        sqlstate=sqlstate,
    )
