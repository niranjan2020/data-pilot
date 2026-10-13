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
    verified_grants: tuple[dict, ...] = ()


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
                   tuple(str(grant.get(k) or "").casefold() for k in IDENTITY)
                   == tuple(str(part).casefold() for part in identity)]
        if len(matches) != 1:
            return PublishedJoinAuthorization(False, ("Required relationship is not currently published for the exact physical join identity (datasource-scoped).",))
        authorized.append(matches[0])
    decision = validate_governed_join_graph(sql, authorized)
    return PublishedJoinAuthorization(bool(decision.allowed), tuple(decision.reasons),
                                      tuple(authorized) if decision.allowed else ())


def authorize_exact_selected_route_sql(
    sql: str, selected_relationships: list[dict],
) -> PublishedJoinAuthorization:
    """Require SQL to use exactly the selected, ordered physical join route.

    This supplements (never replaces) the datasource publication authorization.
    The existing graph validator checks each join key, direction and policy;
    requiring the same number of edges prevents a subset from being accepted.
    """
    import sqlglot
    from sqlglot import exp

    if not selected_relationships:
        return PublishedJoinAuthorization(False, ("No selected route was supplied.",))
    try:
        statements = sqlglot.parse(sql, read="postgres")
        if len(statements) != 1 or not isinstance(statements[0], exp.Select):
            return PublishedJoinAuthorization(False, ("Expected one SELECT.",))
        tree = statements[0]
        with_clause = tree.args.get("with_")
        if with_clause is not None:
            ctes = list(with_clause.expressions)
            if len(ctes) != 1 or not isinstance(ctes[0].this, exp.Select):
                return PublishedJoinAuthorization(False, ("Unsupported CTE route.",))
            tree = ctes[0].this
        elif tree.args.get("from_") and isinstance(tree.args["from_"].this, exp.Subquery):
            tree = tree.args["from_"].this.this
        if not isinstance(tree, exp.Select):
            return PublishedJoinAuthorization(False, ("Unsupported route structure.",))
        joins = tree.args.get("joins") or []
        if len(joins) != len(selected_relationships):
            return PublishedJoinAuthorization(False, ("SQL does not use every selected route edge.",))
        root_clause = tree.args.get("from_")
        if not root_clause or not isinstance(root_clause.this, exp.Table):
            return PublishedJoinAuthorization(False, ("Selected route has no physical root.",))
        root = root_clause.this
        expected_root = selected_relationships[0]
        if (str(root.db or "").casefold(), str(root.name).casefold()) != (
            str(expected_root.get("from_schema") or "").casefold(),
            str(expected_root.get("from_table") or "").split(".")[-1].casefold(),
        ):
            return PublishedJoinAuthorization(False, ("SQL starts from a different relationship root.",))
        for join, edge in zip(joins, selected_relationships):
            target = join.this
            if not isinstance(target, exp.Table) or (
                str(target.db or "").casefold(), str(target.name).casefold()
            ) != (
                str(edge.get("to_schema") or "").casefold(),
                str(edge.get("to_table") or "").split(".")[-1].casefold(),
            ):
                return PublishedJoinAuthorization(False, ("SQL changes the selected relationship order.",))
    except Exception:
        return PublishedJoinAuthorization(False, ("Selected route SQL parsing failed.",))
    decision = validate_governed_join_graph(sql, selected_relationships)
    return PublishedJoinAuthorization(decision.allowed, tuple(decision.reasons))
