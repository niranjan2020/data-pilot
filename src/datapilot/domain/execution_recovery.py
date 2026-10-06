"""Provider-neutral execution recovery evidence."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionRecoveryEvidence:
    """Normalized provider-owned evidence used by the application recovery policy."""

    recoverable: bool
    category: str
    reason: str
    provider: str | None = None
    code: str | None = None
