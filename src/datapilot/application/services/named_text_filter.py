"""Conservative case-insensitive exact matching for explicitly named text attributes.

Only SQL predicates on the requested, governed column are eligible.
Never apply this to published categorical codes or arbitrary free-text search.
"""
from __future__ import annotations

from sqlglot import exp, parse_one


def normalize_named_text_filter(
    sql: str, *,
    attribute_column: str,
    dialect: str = "postgres",
) -> str:
    if not isinstance(sql, str) or not isinstance(attribute_column, str) or not attribute_column.strip():
        raise ValueError("SQL and governed attribute column required")
    tree = parse_one(sql, read=dialect)
    if not isinstance(tree, exp.Select) or any(
        isinstance(node, (exp.Join, exp.Subquery, exp.Union, exp.With))
        for node in tree.walk()
    ):
        return sql
    where = tree.args.get("where")
    if where is None:
        return sql
    predicates = list(where.find_all(exp.In))
    changed = False
    for predicate in predicates:
        column = predicate.this
        if not isinstance(column, exp.Column) or column.name.casefold() != attribute_column.casefold():
            continue
        if len(predicate.expressions) < 2 or not all(
            isinstance(value, exp.Literal) and value.is_string
            for value in predicate.expressions
        ):
            continue
        # Match the complete name exactly, ignoring only case.
        predicate.set("this", exp.Lower(this=column.copy()))
        predicate.set("expressions", [
            exp.Literal.string(str(value.this).lower()) for value in predicate.expressions
        ])
        changed = True
    return tree.sql(dialect=dialect) if changed else sql
