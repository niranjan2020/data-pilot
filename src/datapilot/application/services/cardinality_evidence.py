"""Conservative, deterministic summary of fan-out evidence.

Evidence completeness is not proof of physical key constraints and must never
be interpreted as permission to bypass a fan-out violation.
"""

from __future__ import annotations

from typing import Any


REQUIRED_SIGNALS = (
    "metric_ownership",
    "preaggregation_grain",
    "governed_derived_edge",
    "connected_join_graph",
    "unique_right_join_chain",
    "supported_join_types",
    "outer_aggregate_after_joins",
)


def summarize_cardinality_evidence(
    signals: dict[str, Any],
    *,
    metric: str = "metric",
    relationship: str | None = None,
) -> dict[str, Any]:
    """Return an explainable readiness diagnostic without approving SQL."""
    observed = {name: signals.get(name) is True for name in REQUIRED_SIGNALS}
    missing = [name for name, present in observed.items() if not present]
    return {
        "code": (
            "fanout_cardinality_evidence_complete"
            if not missing else "fanout_cardinality_evidence_incomplete"
        ),
        "status": "passed" if not missing else "skipped",
        "severity": "info",
        "metric": metric,
        "relationship": relationship,
        "evidence": observed,
        "missing_evidence": missing,
        "join_cardinality_safe": False,
        "message": (
            "Structural signals collected; physical uniqueness and metric "
            "preservation remain unproven."
        ),
    }
