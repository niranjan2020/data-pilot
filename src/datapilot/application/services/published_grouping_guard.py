"""Independent SQL AST guard for explicitly requested published group dimensions.

This is a narrow pre-execution check, not a replacement for SQL compilation,
relationship authorization, or the existing SQL correctness verifier.
"""
from __future__ import annotations

import re
from typing import Any

from sqlglot import exp, parse_one


def _terms(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip() + " "


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
    group = tree.args.get("group")
    if not group:
        return ("Requested published dimension is missing from GROUP BY.",)
    by_id = {e.get("id"): e for e in entities}
    table_aliases = {}
    for table in tree.find_all(exp.Table):
        if table.db:
            table_aliases[table.alias_or_name.casefold()] = (
                table.db.casefold(), table.name.casefold()
            )
    for _, d in candidates:
        entity = by_id.get(d["entity_id"])
        if not entity:
            return ("Published dimension owner is missing from semantic context.",)
        expected = (str(entity.get("schema_name") or "").casefold(),
                    str(entity.get("table_name") or "").casefold())
        colname = str(d["column_name"]).casefold()
        matched = False
        for column in group.find_all(exp.Column):
            if column.name.casefold() != colname:
                continue
            if column.table:
                if table_aliases.get(column.table.casefold()) == expected:
                    matched = True
            elif len(set(table_aliases.values())) == 1 and expected in table_aliases.values():
                matched = True
        if not matched:
            return (f"GROUP BY does not use published dimension {d.get('name')}.",)
    return ()
