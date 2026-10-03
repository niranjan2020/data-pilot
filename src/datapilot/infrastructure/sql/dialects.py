"""Translate Data Pilot database dialect names to SQLGlot dialect names."""

from __future__ import annotations

from typing import Optional


_SQLGLOT_DIALECTS = {
    "postgresql": "postgres",
    "postgres": "postgres",
}


def sqlglot_dialect(dialect: Optional[str]) -> str:
    """Return the SQLGlot dialect for a canonical Data Pilot dialect name."""
    if not dialect:
        return "postgres"
    normalized = dialect.strip().lower()
    return _SQLGLOT_DIALECTS.get(normalized, normalized)
