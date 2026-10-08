"""Deterministic join-policy checks for generated PostgreSQL SQL.

Only explicit, fully-qualified physical tables are eligible for enforcement.
Unknown or ambiguous join structure is rejected, never silently rewritten.
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp


@dataclass(frozen=True)
class JoinPolicyDecision:
    allowed: bool
    reasons: tuple[str, ...]


def validate_governed_join_policy(sql: str, relationship: dict) -> JoinPolicyDecision:
    """Validate one published relationship's source-to-target join semantics.

    The caller must supply an authoritative, published relationship. This
    validator is not itself a publishing mechanism or a SQL rewrite engine.
    """
    policy = relationship.get("join_policy")
    if policy not in {"preserve_source", "matched_only"}:
        return JoinPolicyDecision(False, ("Join policy is not configured.",))
    if relationship.get("cardinality") not in {"many_to_one", "one_to_one"}:
        return JoinPolicyDecision(False, ("Join cardinality is not fan-out-safe.",))
    try:
        statements = sqlglot.parse(sql, read="postgres")
        if len(statements) != 1 or not isinstance(statements[0], exp.Select):
            return JoinPolicyDecision(False, ("Expected a single SELECT statement.",))
        tree = statements[0]
    except Exception:
        return JoinPolicyDecision(False, ("SQL parsing failed.",))
    if any(isinstance(node, (exp.Subquery, exp.CTE, exp.Union)) for node in tree.walk()):
        return JoinPolicyDecision(False, ("Nested queries require separate join-policy verification.",))
    source = (relationship["from_schema"].lower(), relationship["from_table"].split(".")[-1].lower())
    target = (relationship["to_schema"].lower(), relationship["to_table"].split(".")[-1].lower())
    tables = tree.find_all(exp.Table)
    occurrences = [(str(t.db or "").lower(), str(t.name).lower(), str(t.alias_or_name).lower()) for t in tables]
    if sum((schema, name) == source for schema, name, _ in occurrences) != 1 or sum((schema, name) == target for schema, name, _ in occurrences) != 1:
        return JoinPolicyDecision(False, ("Source and target must each appear exactly once with explicit schemas.",))
    source_alias = next(alias for schema, name, alias in occurrences if (schema, name) == source)
    target_alias = next(alias for schema, name, alias in occurrences if (schema, name) == target)
    if source_alias == target_alias:
        return JoinPolicyDecision(False, ("Join aliases are ambiguous.",))
    from_table = tree.args.get("from_")
    if from_table is None or not isinstance(from_table.this, exp.Table):
        return JoinPolicyDecision(False, ("Join source must be an explicit table.",))
    root = from_table.this
    if (str(root.db or "").lower(), str(root.name).lower()) != source:
        return JoinPolicyDecision(False, ("Governed joins must preserve the approved source-to-target direction.",))
    joins = tree.args.get("joins") or []
    if len(joins) != 1 or not isinstance(joins[0].this, exp.Table):
        return JoinPolicyDecision(False, ("Expected exactly one explicit governed join.",))
    join = joins[0]
    joined = join.this
    if (str(joined.db or "").lower(), str(joined.name).lower()) != target:
        return JoinPolicyDecision(False, ("Join target differs from the approved relationship.",))
    side = str(join.args.get("side") or "").upper()
    kind = str(join.args.get("kind") or "").upper()
    invalid_type = (side != "LEFT" or kind != "") if policy == "preserve_source" else (side != "" or kind not in {"", "INNER"})
    if invalid_type:
        return JoinPolicyDecision(False, ("Join type violates the approved policy.",))
    on = join.args.get("on")
    if not isinstance(on, exp.EQ):
        return JoinPolicyDecision(False, ("Only the approved key equality is supported.",))
    columns = [on.left, on.right]
    if not all(isinstance(col, exp.Column) for col in columns):
        return JoinPolicyDecision(False, ("Join condition must compare physical key columns.",))
    pairs = {(str(col.table or "").lower(), str(col.name).lower()) for col in columns}
    expected = {(source_alias, relationship["from_column"].lower()), (target_alias, relationship["to_column"].lower())}
    if pairs != expected:
        return JoinPolicyDecision(False, ("Join keys differ from the approved relationship.",))
    return JoinPolicyDecision(True, ())


def validate_governed_join_graph(sql: str, relationships: list[dict]) -> JoinPolicyDecision:
    """Validate every edge of a flat, source-rooted governed join chain.

    Conservative by design: each new table must be joined from an already
    introduced source table, and every edge must have a published policy.
    Nested queries, repeated physical tables, and ambiguous edges fail closed.
    """
    if not relationships:
        return JoinPolicyDecision(False, ("No governed relationships were provided.",))
    try:
        statements = sqlglot.parse(sql, read="postgres")
        if len(statements) != 1 or not isinstance(statements[0], exp.Select):
            return JoinPolicyDecision(False, ("Expected a single SELECT statement.",))
        tree = statements[0]
    except Exception:
        return JoinPolicyDecision(False, ("SQL parsing failed.",))
    # A tightly scoped first nested-query case: a single non-recursive CTE
    # containing the complete governed join graph, followed by a projection
    # over that CTE. No additional joins or nested SQL may escape validation.
    with_clause = tree.args.get("with_")
    if with_clause is not None:
        ctes = list(with_clause.expressions)
        if (with_clause.args.get("recursive") or len(ctes) != 1
                or tree.args.get("joins")
                or any(isinstance(node, (exp.Subquery, exp.Union))
                       for node in tree.walk())):
            return JoinPolicyDecision(False, ("Unsupported nested join structure.",))
        cte = ctes[0]
        inner = cte.this
        root_clause = tree.args.get("from_")
        if (not isinstance(inner, exp.Select)
                or not root_clause or not isinstance(root_clause.this, exp.Table)
                or root_clause.this.db
                or str(root_clause.this.name).lower() != str(cte.alias_or_name).lower()
                or any(isinstance(node, exp.CTE) for node in inner.walk())):
            return JoinPolicyDecision(False, ("CTE projection must reference exactly the governed CTE.",))
        return validate_governed_join_graph(inner.sql(dialect="postgres"), relationships)
    if any(isinstance(node, (exp.Subquery, exp.CTE, exp.Union)) for node in tree.walk()):
        return JoinPolicyDecision(False, ("Nested queries require separate join-policy verification.",))
    root_clause = tree.args.get("from_")
    joins = tree.args.get("joins") or []
    if not root_clause or not isinstance(root_clause.this, exp.Table) or not joins:
        return JoinPolicyDecision(False, ("Expected explicit source and joined tables.",))
    root = root_clause.this
    def identity(table):
        return (str(table.db or "").lower(), str(table.name).lower())
    if not root.db:
        return JoinPolicyDecision(False, ("Every governed table must be schema-qualified.",))
    introduced = {identity(root): str(root.alias_or_name).lower()}
    aliases = {str(root.alias_or_name).lower()}
    for join in joins:
        target = join.this
        if not isinstance(target, exp.Table) or not target.db:
            return JoinPolicyDecision(False, ("Every join target must be an explicit schema-qualified table.",))
        target_id = identity(target)
        target_alias = str(target.alias_or_name).lower()
        if target_id in introduced or target_alias in aliases:
            return JoinPolicyDecision(False, ("Repeated tables or aliases require separate verification.",))
        on = join.args.get("on")
        if not isinstance(on, exp.EQ) or not all(isinstance(col, exp.Column) for col in (on.left, on.right)):
            return JoinPolicyDecision(False, ("Only a single approved key equality is supported.",))
        pairs = {(str(col.table or "").lower(), str(col.name).lower()) for col in (on.left, on.right)}
        candidates = []
        for rel in relationships:
            source_id = (str(rel.get("from_schema") or "").lower(), str(rel.get("from_table") or "").split(".")[-1].lower())
            rel_target = (str(rel.get("to_schema") or "").lower(), str(rel.get("to_table") or "").split(".")[-1].lower())
            if source_id not in introduced or rel_target != target_id:
                continue
            expected = {(introduced[source_id], str(rel.get("from_column") or "").lower()), (target_alias, str(rel.get("to_column") or "").lower())}
            if pairs == expected:
                candidates.append(rel)
        if len(candidates) != 1:
            return JoinPolicyDecision(False, ("Join edge is missing, ambiguous, or not approved.",))
        rel = candidates[0]
        policy = rel.get("join_policy")
        if policy not in {"preserve_source", "matched_only"} or rel.get("cardinality") not in {"many_to_one", "one_to_one"}:
            return JoinPolicyDecision(False, ("Join edge has no enforceable published policy.",))
        side = str(join.args.get("side") or "").upper()
        kind = str(join.args.get("kind") or "").upper()
        if (policy == "preserve_source" and (side != "LEFT" or kind != "")) or (policy == "matched_only" and (side != "" or kind not in {"", "INNER"})):
            return JoinPolicyDecision(False, ("Join type violates the approved policy.",))
        introduced[target_id] = target_alias
        aliases.add(target_alias)
    return JoinPolicyDecision(True, ())
