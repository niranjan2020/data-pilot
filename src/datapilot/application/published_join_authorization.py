"""Authorize generated joins against authoritative persisted publications.

This service must be invoked by the query execution boundary; caller-provided
review flags, publication IDs, and evidence are never trusted as grants.
"""
from __future__ import annotations

from dataclasses import dataclass

from datapilot.application.join_policy_governance import validate_governed_join_graph


IDENTITY = ("from_schema", "from_table", "from_column",
            "to_schema", "to_table", "to_column")


@dataclass(frozen=True)
class PublishedJoinAuthorization:
    allowed: bool
    reasons: tuple[str, ...]


async def authorize_published_joins(
    metadata, source_id: int, sql: str, required_relationships,
) -> PublishedJoinAuthorization:
    """Validate required join identities and actual SQL against DB-backed grants."""
    if not isinstance(source_id, int) or isinstance(source_id, bool) or source_id <= 0:
        return PublishedJoinAuthorization(False, ("Invalid datasource identity.",))
    if not isinstance(sql, str) or not sql.strip():
        return PublishedJoinAuthorization(False, ("Generated SQL is unavailable.",))
    required = list(required_relationships)
    if not required:
        return PublishedJoinAuthorization(False, ("No required relationship contracts.",))
    if any(not isinstance(r, dict) or
           any(not isinstance(r.get(k), str) or not r[k] for k in IDENTITY)
           for r in required):
        return PublishedJoinAuthorization(False, ("Malformed required relationship.",))
    grants = await metadata.list_current_relationship_publications(source_id)
    if not isinstance(grants, list):
        return PublishedJoinAuthorization(False, ("Publication catalog is unavailable.",))
    identities = [tuple(r[k] for k in IDENTITY) for r in required]
    if len(set(identities)) != len(identities):
        return PublishedJoinAuthorization(False, ("Duplicate required relationships.",))
    authorized = []
    for identity in identities:
        matches = [grant for grant in grants
                   if isinstance(grant, dict) and
                   tuple(grant.get(k) for k in IDENTITY) == identity]
        if len(matches) != 1:
            return PublishedJoinAuthorization(False, ("Required relationship is not currently published.",))
        authorized.append(matches[0])
    decision = validate_governed_join_graph(sql, authorized)
    return PublishedJoinAuthorization(bool(decision.allowed), tuple(decision.reasons))
