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
    try:
        tree = parse_one(sql, read=dialect)
    except Exception:
        # Preserve existing SQL validator ownership of malformed SQL.
        return sql
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


_TEXT_TYPES = {"text", "varchar", "character varying", "character", "char", "citext", "string", "nvarchar"}
_NON_TEXT_TYPES = {"integer", "int", "bigint", "smallint", "numeric", "decimal", "float", "double", "boolean", "bool", "date", "timestamp", "uuid"}
_CODE_KEYS = ("value_mappings", "categorical_mappings", "enum_values", "allowed_values", "canonical_values")


def normalize_governed_text_filters(
    sql: str, *, governed_entities: list[dict], physical_schema=None, dialect: str = "postgres"
) -> str:
    """Normalize exact multi-value text comparisons using trusted semantic columns.

    An untyped attribute is not proof of text. Mapped/code attributes are
    excluded regardless of type. The existing SQL validator still validates
    the resulting statement before execution.
    """
    if not isinstance(governed_entities, list):
        return sql
    eligible: set[str] = set()
    excluded: set[str] = set()
    for entity in governed_entities:
        if not isinstance(entity, dict):
            continue
        for attribute in entity.get("attributes") or []:
            if not isinstance(attribute, dict):
                continue
            name = attribute.get("column_name") or attribute.get("physical_column") or attribute.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            key = name.casefold()
            typ = str(attribute.get("data_type") or attribute.get("type") or "").strip().casefold()
            if any(attribute.get(k) for k in _CODE_KEYS) or typ in _NON_TEXT_TYPES:
                excluded.add(key)
            elif typ in _TEXT_TYPES or typ.startswith(("varchar(", "character varying(", "nvarchar(")):
                eligible.add(key)
    if physical_schema is not None:
        try:
            parsed = parse_one(sql, read=dialect)
            tables = list(parsed.find_all(exp.Table))
            if len(tables) == 1:
                source = tables[0]
                matches = [
                    item for item in physical_schema.tables
                    if item.name.casefold() == source.name.casefold()
                    and (not source.db or (item.schema_name or "").casefold() == source.db.casefold())
                ]
                if len(matches) == 1:
                    for item in matches[0].columns:
                        typ = str(item.data_type).strip().casefold()
                        key = item.name.casefold()
                        if typ in _TEXT_TYPES or typ.startswith(("varchar(", "character varying(", "nvarchar(")):
                            eligible.add(key)
                        elif typ in _NON_TEXT_TYPES:
                            excluded.add(key)
        except (AttributeError, TypeError, ValueError):
            pass
    eligible.difference_update(excluded)
    if not eligible:
        return sql
    try:
        tree = parse_one(sql, read=dialect)
    except Exception:
        return sql
    if not isinstance(tree, exp.Select) or any(
        isinstance(node, (exp.Join, exp.Subquery, exp.Union, exp.With))
        for node in tree.walk()
    ):
        return sql
    where = tree.args.get("where")
    if where is None:
        return sql
    changed = False
    for predicate in where.find_all(exp.In):
        column = predicate.this
        if not isinstance(column, exp.Column) or column.name.casefold() not in eligible:
            continue
        if len(predicate.expressions) < 2 or not all(
            isinstance(v, exp.Literal) and v.is_string for v in predicate.expressions
        ):
            continue
        predicate.set("this", exp.Lower(this=column.copy()))
        predicate.set("expressions", [
            exp.Literal.string(str(v.this).lower()) for v in predicate.expressions
        ])
        changed = True
    return tree.sql(dialect=dialect) if changed else sql
