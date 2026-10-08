"""Bounded, read-only referential-integrity checks for a reviewed relationship.

Checks do not publish joins or expose customer data. Null keys are reported
separately from unmatched non-null keys.
"""
from __future__ import annotations

from dataclasses import dataclass

from datapilot.infrastructure.database.relationship_cardinality import _qualified


@dataclass(frozen=True)
class ReferentialIntegrityEvidence:
    checked: bool
    unmatched_references: bool | None = None
    nullable_references: bool | None = None
    publishable: bool = False
    reason: str = ""


async def verify_referential_integrity(provider, relationship: dict) -> ReferentialIntegrityEvidence:
    """Check the source-to-target reference direction, never infer join semantics.

    Each EXISTS query returns only a boolean. A transaction-local timeout bounds
    execution, and errors fail closed without exposing database diagnostics.
    """
    source, source_key = _qualified(
        relationship["from_schema"], relationship["from_table"], relationship["from_column"]
    )
    target, target_key = _qualified(
        relationship["to_schema"], relationship["to_table"], relationship["to_column"]
    )
    try:
        pool = await provider._get_pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                await connection.execute("SET LOCAL statement_timeout = '5000ms'")
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        f"SELECT EXISTS (SELECT 1 FROM {source} AS s "
                        f"WHERE s.{source_key} IS NULL LIMIT 1)"
                    )
                    null_row = await cursor.fetchone()
                    if null_row is None:
                        return ReferentialIntegrityEvidence(False, reason="Null-key check returned no result.")
                    await cursor.execute(
                        f"SELECT EXISTS (SELECT 1 FROM {source} AS s "
                        f"WHERE s.{source_key} IS NOT NULL AND NOT EXISTS "
                        f"(SELECT 1 FROM {target} AS t WHERE t.{target_key} = s.{source_key}) "
                        f"LIMIT 1)"
                    )
                    unmatched_row = await cursor.fetchone()
                    if unmatched_row is None:
                        return ReferentialIntegrityEvidence(False, reason="Unmatched-key check returned no result.")
                    nullable = bool(null_row[0])
                    unmatched = bool(unmatched_row[0])
                    return ReferentialIntegrityEvidence(
                        checked=True,
                        unmatched_references=unmatched,
                        nullable_references=nullable,
                        reason=(
                            "Unmatched non-null references found; join publication is blocked."
                            if unmatched else
                            "No unmatched non-null references found; null references require an explicit join policy."
                            if nullable else
                            "No null or unmatched source references found; publication remains gated."
                        ),
                    )
    except Exception:
        return ReferentialIntegrityEvidence(False, reason="Referential-integrity verification unavailable or timed out.")
