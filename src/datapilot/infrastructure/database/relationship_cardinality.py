"""Read-only, bounded PostgreSQL evidence for reviewed join cardinality.

No sampled data, raw rows, or identifiers are returned. This module never publishes joins.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _qualified(schema: str, table: str, column: str) -> tuple[str, str]:
    if not all(_IDENTIFIER.fullmatch(part) for part in (schema, table, column)):
        raise ValueError("Unsupported SQL identifier; verification denied.")
    return f'"{schema}"."{table}"', f'"{column}"'


@dataclass(frozen=True)
class CardinalityEvidence:
    checked: bool
    cardinality_holds: bool
    publishable: bool = False
    reason: str = ""


async def verify_live_cardinality(provider, relationship: dict) -> CardinalityEvidence:
    """Check uniqueness on each cardinality-constrained side without scanning full result sets.

    PostgreSQL EXISTS stops at the first duplicate, but large tables may still
    require work. A database-enforced statement timeout is mandatory.
    """
    kind = relationship["cardinality"]
    if kind not in {"many_to_one", "one_to_many", "one_to_one"}:
        return CardinalityEvidence(False, False, reason="Unsupported or fan-out-prone cardinality.")
    from_table, from_col = _qualified(relationship["from_schema"], relationship["from_table"], relationship["from_column"])
    to_table, to_col = _qualified(relationship["to_schema"], relationship["to_table"], relationship["to_column"])
    checks = []
    if kind in {"many_to_one", "one_to_one"}:
        checks.append((to_table, to_col))
    if kind in {"one_to_many", "one_to_one"}:
        checks.append((from_table, from_col))
    try:
        pool = await provider._get_pool()
        async with pool.connection() as conn:
            async with conn.transaction():
                await conn.execute("SET TRANSACTION READ ONLY")
                await conn.execute("SET LOCAL statement_timeout = '5000ms'")
                for table, column in checks:
                    # NULLs cannot match on SQL equality; exclude them from duplicate detection.
                    sql = (f"SELECT EXISTS (SELECT 1 FROM {table} WHERE {column} IS NOT NULL "
                           f"GROUP BY {column} HAVING COUNT(*) > 1 LIMIT 1)")
                    async with conn.cursor() as cursor:
                        await cursor.execute(sql)
                        row = await cursor.fetchone()
                        if row and row[0]:
                            return CardinalityEvidence(True, False, reason="Duplicate join keys violate the reviewed cardinality.")
        return CardinalityEvidence(True, True, reason="Live uniqueness checks passed; publication remains gated.")
    except Exception:
        # Do not expose database error messages, connection details, or row values.
        return CardinalityEvidence(False, False, reason="Live verification unavailable or timed out.")
