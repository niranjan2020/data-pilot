"""Conservative AST repair for invalid GROUP BY UNNEST expressions.

Only a single-source SELECT with one identical UNNEST expression in the
projection and GROUP BY is rewritten. Complex shapes fail closed.
"""
from __future__ import annotations

import re
from sqlglot import exp, parse_one
from datapilot.application.services.query_correctness import sqlglot_dialect


def repair_grouped_array_expansion(sql: str, checks: list[dict], *, dialect: str = "postgres") -> str | None:
    failed = [c for c in checks if c.get("status") == "failed"]
    if len(failed) != 1 or failed[0].get("code") != "array_expansion_grouping_violation":
        return None
    try:
        dialect = sqlglot_dialect(dialect)
        tree = parse_one(sql, read=dialect)
        if not isinstance(tree, exp.Select) or any(
            isinstance(n, (exp.Join, exp.Subquery, exp.CTE, exp.Union, exp.Window, exp.Having))
            for n in tree.walk()
        ):
            return None
        if len(list(tree.find_all(exp.Table))) != 1 or tree.args.get("group") is None:
            return None
        group = tree.args["group"]
        # Resolve only a unique projected UNNEST with one physical array column.
        projections = [
            (i, p, p.this if isinstance(p, exp.Alias) else p)
            for i, p in enumerate(tree.expressions, 1)
            if re.fullmatch(
                r'UNNEST\s*\(\s*(?:[\w"]+\.)?[\w"]+\s*\)',
                (p.this if isinstance(p, exp.Alias) else p).sql(dialect=dialect),
                re.I,
            )
        ]
        if len(projections) != 1:
            return None
        index, projection, unnest = projections[0]
        # sqlglot represents PostgreSQL UNNEST with different expression
        # classes across versions. Verify its SQL shape and column lineage
        # instead of requiring exp.Unnest specifically.
        columns = list(unnest.find_all(exp.Column))
        if len(columns) != 1:
            return None
        target_sql = unnest.sql(dialect=dialect)
        matches = []
        for item in group.expressions:
            if item.sql(dialect=dialect) == target_sql:
                matches.append(item)
            elif isinstance(item, exp.Column) and not item.table and isinstance(projection, exp.Alias) and item.name.casefold() == projection.alias.casefold():
                matches.append(item)
            elif isinstance(item, exp.Literal) and item.is_int and int(item.this) == index:
                matches.append(item)
        if len(matches) != 1:
            return None
        target = matches[0]
        if any(re.search(r"\bUNNEST\s*\(", item.sql(dialect=dialect), re.I) and item is not target for item in group.expressions):
            return None
        # Reparse the lateral relation instead of manipulating raw SQL tokens.
        from_clause = tree.args.get("from_")
        if from_clause is None:
            return None
        alias = "_dp_array_value"
        relation = parse_one(
            "SELECT * FROM public.placeholder CROSS JOIN LATERAL "
            f"{target_sql} AS _dp_expanded({alias})", read=dialect,
        )
        joins = relation.args.get("joins") or []
        if len(joins) != 1:
            return None
        tree.append("joins", joins[0].copy())
        replacement = exp.column(alias, table="_dp_expanded")
        group.set("expressions", [
            replacement.copy() if g is target else g.copy()
            for g in group.expressions
        ])
        if isinstance(projection, exp.Alias):
            projection.set("this", replacement.copy())
        else:
            tree.set("expressions", [
                replacement.copy() if p is projection else p
                for p in tree.expressions
            ])
        return tree.sql(dialect=dialect)
    except Exception:
        return None
