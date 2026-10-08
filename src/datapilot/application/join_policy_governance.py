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
