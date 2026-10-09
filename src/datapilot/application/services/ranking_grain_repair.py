"""Conservative repair for unintended extra dimensions in top-N aggregates."""
from __future__ import annotations
from sqlglot import exp, parse_one
from datapilot.infrastructure.sql.dialects import sqlglot_dialect


def repair_ranking_grain(sql: str, checks: list[dict], *, dialect: str = "postgres") -> str | None:
    failed = [c for c in checks if c.get("status") == "failed"]
    if len(failed) != 1 or failed[0].get("code") != "ranking_grain_violation":
        return None
    extra = set(failed[0].get("extra_columns") or [])
    if not extra:
        return None
    try:
        normalized = sqlglot_dialect(dialect)
        tree = parse_one(sql, read=normalized)
        if not isinstance(tree, exp.Select) or tree.args.get("distinct") or any(
            isinstance(n, (exp.Join, exp.Subquery, exp.Union, exp.With, exp.Having, exp.Window, exp.Qualify))
            for n in tree.walk()
        ):
            return None
        if len(list(tree.find_all(exp.Table))) != 1 or not tree.args.get("group") or not tree.args.get("order"):
            return None
        group = tree.args["group"]
        removable = [
            expression for expression in group.expressions
            if isinstance(expression, exp.Column) and expression.name.casefold() in extra
        ]
        if len(removable) != len(extra):
            return None
        selections = [
            expression for expression in tree.expressions
            if isinstance(expression, exp.Column) and expression.name.casefold() in extra
        ]
        if len(selections) != len(extra):
            return None
        # Never remove columns used in aggregate expressions, HAVING, ordering,
        # or other selected calculations. WHERE filters are intentionally retained.
        for node in [*tree.expressions, *tree.args["order"].expressions]:
            if node in selections:
                continue
            if any(col.name.casefold() in extra for col in node.find_all(exp.Column)):
                return None
        tree.set("expressions", [e for e in tree.expressions if e not in selections])
        group.set("expressions", [e for e in group.expressions if e not in removable])
        return tree.sql(dialect=normalized)
    except Exception:
        return None
