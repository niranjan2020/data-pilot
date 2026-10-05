"""Deterministic correctness checks between governed context and generated SQL."""

from __future__ import annotations

from typing import Any, Iterable


def _normalise(name: str) -> str:
    return str(name or "").strip().strip('"').casefold()


def _within_governed_scope(table: str, governed_tables: Iterable[str]) -> bool:
    candidate = _normalise(table)
    candidate_leaf = candidate.rsplit(".", 1)[-1]
    for governed in governed_tables:
        allowed = _normalise(governed)
        if candidate == allowed:
            return True
        # Validators may report either schema-qualified or unqualified names.
        if candidate_leaf == allowed.rsplit(".", 1)[-1]:
            return True
    return False


def assess_query_correctness(
    *,
    affected_tables: Iterable[str],
    governed_tables: Iterable[str],
) -> list[dict[str, Any]]:
    """Return deterministic pre-execution alignment checks.

    This deliberately does not ask an LLM to judge its own SQL. The first
    production invariant is physical-scope containment: generated SQL may only
    touch tables selected by the governed semantic/physical context.
    """
    affected = [str(item) for item in affected_tables if str(item or "").strip()]
    governed = [str(item) for item in governed_tables if str(item or "").strip()]

    if not governed:
        return [{
            "code": "governed_scope_unavailable",
            "status": "skipped",
            "severity": "info",
            "message": "No governed physical-table boundary was available for scope verification.",
        }]

    unexpected = [
        table for table in affected
        if not _within_governed_scope(table, governed)
    ]
    if unexpected:
        return [{
            "code": "physical_scope_violation",
            "status": "failed",
            "severity": "error",
            "unexpected_tables": unexpected,
            "governed_tables": governed,
            "message": "Generated SQL references table(s) outside the governed physical context: "
            + ", ".join(unexpected),
        }]

    return [{
        "code": "physical_scope_alignment",
        "status": "passed",
        "severity": "info",
        "affected_tables": affected,
        "governed_tables": governed,
        "message": "All SQL table references are within the governed physical context.",
    }]
