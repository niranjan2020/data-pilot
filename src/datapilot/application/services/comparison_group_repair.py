"""Conservative SQL AST repair for missing comparison cohort grouping.

Only a simple single-source aggregate SELECT can be repaired. Any uncertainty
returns None so the caller retains its existing fail-closed rejection.
"""
from __future__ import annotations

from sqlglot import exp, parse_one


def repair_missing_comparison_groups(
    sql: str, checks: list[dict], *, dialect: str = "postgres"
) -> str | None:
    failures = [c for c in checks if c.get("status") == "failed"]
    if len(failures) != 1 or failures[0].get("code") != "comparison_dimension_violation":
        return None
    missing = failures[0].get("missing_columns")
    if not isinstance(missing, list) or not missing or any(
        not isinstance(name, str) or not name.isidentifier() for name in missing
    ):
        return None
    try:
        tree = parse_one(sql, read=dialect)
    except Exception:
        return None
    if not isinstance(tree, exp.Select) or tree.args.get("distinct") is not None or any(
        isinstance(node, (exp.Join, exp.Subquery, exp.Union, exp.With, exp.Having,
                          exp.Window, exp.Qualify))
        for node in tree.walk()
    ):
        return None
    group = tree.args.get("group")
    where = tree.args.get("where")
    if group is None or where is None:
        return None
    tables = list(tree.find_all(exp.Table))
    if len(tables) != 1:
        return None
    for name in missing:
        candidates = []
        for predicate in where.find_all(exp.In):
            operand = predicate.this
            if isinstance(operand, exp.Lower):
                operand = operand.this
            if isinstance(operand, exp.Column) and operand.name.casefold() == name.casefold():
                if len(predicate.expressions) >= 2 and all(
                    isinstance(value, exp.Literal) for value in predicate.expressions
                ):
                    candidates.append(operand)
        if len(candidates) != 1:
            return None
        column = candidates[0].copy()
        if column.table and column.table.casefold() not in {
            tables[0].name.casefold(), (tables[0].alias or "").casefold()
        }:
            return None
        tree.append("expressions", column.copy())
        group.append("expressions", column)
    return tree.sql(dialect=dialect)
