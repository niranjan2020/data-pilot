"""Deterministic policy for bounded SQL correction eligibility."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


RECOVERABLE_CORRECTNESS_CODES = frozenset({
    "metric_expression_violation",
    "grouping_dimension_violation",
    "comparison_contract_violation",
    "filter_violation",
    "relationship_violation",
    "join_fanout_violation",
    "time_filter_violation",
    "time_grain_violation",
    "time_comparison_violation",
    "physical_scope_violation",
    # A single bounded regeneration is allowed; the exact same governed
    # publication, dataset, array and categorical checks still run afterward.
    "relationship_publication_violation",
    "dataset_selection_violation",
    "array_expansion_grouping_violation",
    "categorical_comparison_filter_violation",
})

UNVERIFIABLE_CORRECTNESS_CODES = frozenset({
    "metric_expression_verification_unavailable",
    "grouping_verification_unavailable",
    "filter_verification_unavailable",
    "relationship_verification_unavailable",
    "fanout_verification_unavailable",
    "time_verification_unavailable",
    "governed_scope_unavailable",
})


@dataclass(frozen=True)
class SQLCorrectionDecision:
    recoverable: bool
    category: str
    feedback: tuple[dict[str, Any], ...] = ()
    reason: str = ""


def classify_sql_correction(
    *,
    validation_errors: Iterable[Any] = (),
    correctness_checks: Iterable[dict[str, Any]] = (),
    policy_errors: Iterable[Any] = (),
) -> SQLCorrectionDecision:
    """Classify one failed SQL proposal without performing a retry.

    Safety/policy failures and unverifiable governed checks remain hard failures.
    Deterministic governed violations are eligible for one future bounded
    correction attempt because they provide structured, machine-readable feedback.
    """
    policy = tuple(policy_errors)
    if policy:
        return SQLCorrectionDecision(
            recoverable=False,
            category="policy",
            reason="Execution-policy failures are not eligible for SQL correction.",
        )

    validation = tuple(validation_errors)
    if validation:
        return SQLCorrectionDecision(
            recoverable=False,
            category="validation",
            reason="AST/safety validation failures remain hard failures.",
        )

    checks = tuple(correctness_checks)
    unavailable = tuple(
        check for check in checks
        if str(check.get("code") or "") in UNVERIFIABLE_CORRECTNESS_CODES
    )
    if unavailable:
        return SQLCorrectionDecision(
            recoverable=False,
            category="governed_correctness",
            feedback=unavailable,
            reason="A required correctness property could not be verified.",
        )

    violations = tuple(
        check for check in checks
        if check.get("status") == "failed"
        and str(check.get("code") or "") in RECOVERABLE_CORRECTNESS_CODES
    )
    unknown_failures = tuple(
        check for check in checks
        if check.get("status") == "failed"
        and str(check.get("code") or "") not in RECOVERABLE_CORRECTNESS_CODES
    )
    if unknown_failures:
        return SQLCorrectionDecision(
            recoverable=False,
            category="governed_correctness",
            feedback=unknown_failures,
            reason="Unknown governed correctness failures remain hard failures.",
        )
    if violations:
        return SQLCorrectionDecision(
            recoverable=True,
            category="governed_correctness",
            feedback=violations,
            reason="Structured governed correctness violations are eligible for one bounded correction attempt.",
        )

    return SQLCorrectionDecision(
        recoverable=False,
        category="none",
        reason="No recoverable SQL failure was supplied.",
    )
