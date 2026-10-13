"""Independent SQL AST guard for explicitly requested published group dimensions.

This is a narrow pre-execution check, not a replacement for SQL compilation,
relationship authorization, or the existing SQL correctness verifier.
"""
from __future__ import annotations

import re
from typing import Any

from sqlglot import exp, parse_one


def _terms(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9_]+", " ", text.casefold()).strip() + " " 



def _physical_lineage(
    select: exp.Select,
    expression: exp.Expression,
    *,
    ctes: dict[str, exp.Select],
    seen: frozenset[str] = frozenset(),
) -> set[tuple[str, str, str]]:
    """Resolve direct column lineage through named CTEs and derived SELECTs.

    Computed expressions, stars, ambiguous qualifiers and recursive CTEs are
    deliberately not accepted as proof of an approved physical dimension.
    """
    if isinstance(expression, exp.Alias):
        expression = expression.this
    if not isinstance(expression, exp.Column):
        return set()
    # Resolve only sources belonging to this SELECT. Descendant query scopes
    # must not contribute tables or override aliases in the outer query.
    tables = {}
    from_clause = select.args.get("from_")
    sources = []
    if from_clause and from_clause.this is not None:
        sources.append(from_clause.this)
    sources.extend(join.this for join in select.args.get("joins") or []
                   if join.this is not None)
    for source in sources:
        if isinstance(source, exp.Table):
            alias = source.alias_or_name.casefold()
            if alias in tables:
                return set()
            if source.db:
                tables[alias] = ("physical", source.db.casefold(), source.name.casefold())
            elif source.name.casefold() in ctes:
                tables[alias] = ("derived", source.name.casefold())
            else:
                # Unqualified, unrecognized relations cannot establish lineage.
                return set()
        elif isinstance(source, exp.Subquery):
            if not isinstance(source.this, exp.Select) or not source.alias:
                return set()
            alias = source.alias.casefold()
            if alias in tables:
                return set()
            tables[alias] = ("inline", source.this)
        else:
            # Unsupported table-valued functions / lateral sources must not
            # accidentally authorize a similarly named physical column.
            return set()
    qualifier = expression.table.casefold() if expression.table else ""
    if not qualifier:
        if len(tables) != 1:
            return set()
        qualifier = next(iter(tables))
    source = tables.get(qualifier)
    if not source:
        return set()
    if source[0] == "physical":
        return {(source[1], source[2], expression.name.casefold())}
    key = source[1] if source[0] == "derived" else qualifier
    if key in seen:
        return set()
    inner = ctes.get(key) if source[0] == "derived" else source[1]
    if not isinstance(inner, exp.Select):
        return set()
    matching = [
        item for item in inner.expressions
        if (item.alias_or_name or "").casefold() == expression.name.casefold()
    ]
    if len(matching) != 1:
        return set()
    return _physical_lineage(
        inner, matching[0], ctes=ctes, seen=seen | {key}
    )


def _group_expressions(select: exp.Select) -> list[exp.Expression]:
    group = select.args.get("group")
    if not group:
        return []
    resolved = []
    for item in group.expressions:
        if isinstance(item, exp.Literal) and item.is_int:
            index = int(item.this) - 1
            if not 0 <= index < len(select.expressions):
                return []
            resolved.append(select.expressions[index])
        elif isinstance(item, exp.Column) and not item.table:
            aliases = [
                projection for projection in select.expressions
                if isinstance(projection, exp.Alias)
                and projection.alias.casefold() == item.name.casefold()
            ]
            resolved.append(aliases[0] if len(aliases) == 1 else item)
        else:
            resolved.append(item)
    return resolved

def check_published_grouping(
    sql: str,
    question: str,
    dimensions: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    *,
    dialect: str = "postgres",
) -> tuple[str, ...]:
    """Return violations; empty means no violation proved by this narrow guard.

    Only explicitly mentioned, uniquely published dimensions are enforceable.
    Reject ambiguous matches rather than picking an arbitrary owning entity.
    """
    normalized = _terms(question)
    # Only grouping intent belongs to this guard; dimensions mentioned solely
    # in filters must be validated by the separate filter-alignment gate.
    grouping_intent = re.search(r"\b(?:grouped by|group by|by|per)\s+(.+)", normalized)
    if grouping_intent is None:
        return ()
    normalized = " " + grouping_intent.group(1).strip() + " "
    candidates = []
    for d in dimensions:
        if type(d.get("entity_id")) is not int or not d.get("column_name"):
            continue
        names = [d.get("name"), *(d.get("synonyms") or [])]
        matched = [
            _terms(name).strip() for name in names
            if isinstance(name, str) and _terms(name).strip()
            and f" {_terms(name).strip()} " in normalized
        ]
        if matched:
            candidates.append((max(matched, key=len), d))
    if not candidates:
        return ()
    # The longer phrase wins only when it contains the shorter phrase.
    candidates = [(phrase, d) for phrase, d in candidates
                  if not any(phrase != other and f" {phrase} " in f" {other} "
                             for other, _ in candidates)]
    for phrase, _ in candidates:
        owners = {(d["entity_id"], str(d["column_name"]).casefold())
                  for p, d in candidates if p == phrase}
        if len(owners) != 1:
            return ("Ambiguous published grouping dimension.",)
    try:
        tree = parse_one(sql, read=dialect)
    except Exception:
        return ("Cannot parse SQL for grouping authorization.",)
    if tree is None:
        return ("Empty SQL for grouping authorization.",)
    ctes = {}
    for cte in tree.find_all(exp.CTE):
        # Duplicate names or unsupported CTE shapes cannot provide trusted
        # physical lineage; never silently let the last definition win.
        name = cte.alias.casefold()
        if not name or name in ctes or not isinstance(cte.this, exp.Select):
            return ("Cannot verify published dimension through ambiguous CTEs.",)
        ctes[name] = cte.this
    if not isinstance(tree, exp.Select):
        return ("Cannot verify published grouping on this SQL query shape.",)
    grouped = _group_expressions(tree)
    if not grouped:
        return ("Requested published dimension is missing from GROUP BY.",)
    by_id = {e.get("id"): e for e in entities}
    grouped_lineage = set()
    for expression in grouped:
        grouped_lineage.update(_physical_lineage(tree, expression, ctes=ctes))
    projected_lineage = set()
    for expression in tree.expressions:
        projected_lineage.update(_physical_lineage(tree, expression, ctes=ctes))
    for _, dimension in candidates:
        owner = by_id.get(dimension["entity_id"])
        if owner is None:
            return ("Published dimension owner is missing from semantic context.",)
        physical = (
            str(owner.get("schema_name") or "").casefold(),
            str(owner.get("table_name") or "").casefold(),
            str(dimension["column_name"]).casefold(),
        )
        if physical not in grouped_lineage:
            return (f"GROUP BY does not use published dimension {dimension.get('name')}.",)
        if physical not in projected_lineage:
            return (f"SELECT does not project published dimension {dimension.get('name')}.",)
    return ()
