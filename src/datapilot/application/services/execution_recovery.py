"""Fail-closed application policy for provider-owned execution recovery evidence."""

from __future__ import annotations

from dataclasses import dataclass

from datapilot.domain.execution_recovery import ExecutionRecoveryEvidence


@dataclass(frozen=True)
class ExecutionRecoveryDecision:
    recoverable: bool
    category: str
    reason: str
    provider: str | None = None
    code: str | None = None

    @property
    def sqlstate(self) -> str | None:
        """Backward-compatible trace alias while PostgreSQL is the only provider."""
        return self.code


def classify_execution_error(
    *,
    evidence: ExecutionRecoveryEvidence | None = None,
) -> ExecutionRecoveryDecision:
    """Apply the application recovery gate to provider-classified evidence.

    The application layer does not interpret vendor codes. Missing provider
    evidence is terminal, preserving B2's fail-closed behavior.
    """
    if evidence is None:
        return ExecutionRecoveryDecision(
            recoverable=False,
            category="unknown",
            reason="Execution failure has no provider recovery classification.",
        )

    return ExecutionRecoveryDecision(
        recoverable=bool(evidence.recoverable),
        category=evidence.category,
        reason=evidence.reason,
        provider=evidence.provider,
        code=evidence.code,
    )
