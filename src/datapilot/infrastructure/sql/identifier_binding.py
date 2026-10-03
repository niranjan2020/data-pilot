"""Bind generated SQL identifiers to exact physical catalog casing."""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from datapilot.domain.models import SchemaMetadata
from datapilot.infrastructure.sql.dialects import sqlglot_dialect


def bind_physical_identifiers(sql: str, schema: SchemaMetadata, dialect: str) -> str:
    """Quote identifiers using exact names discovered from the physical database.

    LLMs may emit PostgreSQL identifiers without quotes. PostgreSQL folds those
    names to lowercase, which breaks databases that were created with quoted
    mixed-case identifiers (for example AdventureWorks). This AST pass maps
    case-insensitively back to the catalog and quotes the canonical names.
    """
    target = sqlglot_dialect(dialect)
    statements = sqlglot.parse(sql, read=target)
    if len(statements) != 1:
        return sql
    statement = statements[0]

    tables: dict[tuple[str, str], object] = {}
    tables_by_name: dict[str, list[object]] = {}
    for table in schema.tables:
        schema_name = table.schema_name or schema.schema_name or ""
        tables[(schema_name.lower(), table.name.lower())] = table
        tables_by_name.setdefault(table.name.lower(), []).append(table)

    alias_to_table: dict[str, object] = {}
    for node in statement.find_all(exp.Table):
        db_name = node.db or ""
        table_name = node.name
        physical = tables.get((db_name.lower(), table_name.lower())) if db_name else None
        if physical is None:
            candidates = tables_by_name.get(table_name.lower(), [])
            if len(candidates) == 1:
                physical = candidates[0]
        if physical is None:
            continue

        physical_schema = physical.schema_name or schema.schema_name
        node.set("this", exp.to_identifier(physical.name, quoted=True))
        if physical_schema:
            node.set("db", exp.to_identifier(physical_schema, quoted=True))

        alias = node.alias
        if alias:
            alias_to_table[alias.lower()] = physical
        alias_to_table[physical.name.lower()] = physical

    for column in statement.find_all(exp.Column):
        qualifier = column.table
        physical = alias_to_table.get(qualifier.lower()) if qualifier else None
        if physical is None:
            matches = [
                table for table in schema.tables
                if any(c.name.lower() == column.name.lower() for c in table.columns)
            ]
            if len(matches) == 1:
                physical = matches[0]
        if physical is None:
            continue
        exact = next(
            (c.name for c in physical.columns if c.name.lower() == column.name.lower()),
            None,
        )
        if exact:
            column.set("this", exp.to_identifier(exact, quoted=True))

    return statement.sql(dialect=target)
