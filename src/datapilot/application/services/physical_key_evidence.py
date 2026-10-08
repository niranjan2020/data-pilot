"""Validate explicit governed physical unique-key declarations.

Never infer a database UNIQUE constraint from relationship cardinality alone.
This module is advisory until a trusted catalog supplies verified constraints.
"""

from __future__ import annotations

from typing import Any


def assess_declared_unique_key(
    relationship: dict[str, Any],
    *,
    side: str = "to",
) -> dict[str, Any]:
    """Inspect trusted, explicitly verified single-column uniqueness metadata."""
    if side not in {"from", "to"}:
        raise ValueError("side must be 'from' or 'to'")
    table = str(relationship.get(f"{side}_table") or "").strip().casefold()
    schema = str(relationship.get(f"{side}_schema") or "").strip().casefold()
    column = str(relationship.get(f"{side}_column") or "").strip().casefold()
    verified = relationship.get(f"{side}_unique_key_verified") is True
    declared = relationship.get(f"{side}_unique_columns")
    columns = (
        [str(item).strip().casefold() for item in declared]
        if isinstance(declared, (list, tuple)) and
        all(isinstance(item, str) for item in declared)
        else []
    )
    # A composite constraint cannot prove uniqueness of a single join column.
    unique = bool(verified and table and schema and column and columns == [column])
    return {
        "code": "fanout_physical_unique_key_verified"
        if unique else "fanout_physical_unique_key_unverified",
        "status": "passed" if unique else "skipped",
        "severity": "info",
        "relationship": relationship.get("name"),
        "side": side,
        "table": f"{schema}.{table}" if schema and table else None,
        "column": column or None,
        "unique_key_verified": unique,
        "join_cardinality_safe": False,
        "message": (
            "A verified single-column unique-key declaration matches the join key."
            if unique else
            "No verified single-column physical unique-key declaration matches the join key."
        ),
    }
