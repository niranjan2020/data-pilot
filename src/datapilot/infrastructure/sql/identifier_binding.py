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
    physical_table_names: dict[str, str] = {}
    query_aliases: set[str] = set()
    referenced_tables: list[object] = []
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

        referenced_tables.append(physical)
        physical_schema = physical.schema_name or schema.schema_name
        node.set("this", exp.to_identifier(physical.name, quoted=True))
        if physical_schema:
            node.set("db", exp.to_identifier(physical_schema, quoted=True))

        # sqlglot's Table.alias property falls back to the table name when no
        # explicit alias exists. Inspect the AST alias node so only genuine
        # query aliases are recorded here.
        alias_expression = node.args.get("alias")
        alias = alias_expression.name if alias_expression is not None else ""
        if alias:
            alias_key = alias.lower()
            alias_to_table[alias_key] = physical
            query_aliases.add(alias_key)
            # PostgreSQL also folds unquoted aliases to lowercase. Quote the
            # alias itself so generated T1/t1 references have one canonical
            # spelling throughout the statement.
            alias_expression.set("this", exp.to_identifier(alias, quoted=True))
        else:
            # Once the physical table is schema-qualified and quoted, a
            # qualifier such as Product.ProductID is no longer a valid reference
            # to it in PostgreSQL. Treat the physical table name as a lookup key
            # only; column qualifiers are removed below for unaliased tables.
            pass
        alias_to_table[physical.name.lower()] = physical
        physical_table_names[physical.name.lower()] = physical.name

    for column in statement.find_all(exp.Column):
        qualifier = column.table
        qualifier_key = qualifier.lower() if qualifier else ""
        physical = alias_to_table.get(qualifier_key) if qualifier else None
        if physical is None:
            # Resolve unqualified columns only against tables actually present in
            # this SQL statement. The governed schema can contain several tables
            # with common names such as ID/Name; searching the whole schema makes
            # an otherwise unambiguous single-table query impossible to bind.
            search_tables = referenced_tables or schema.tables
            matches = [
                table for table in search_tables
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
        if qualifier and qualifier_key in query_aliases:
            # Keep alias-qualified columns, but bind the qualifier to the exact
            # explicit alias casing used in the FROM/JOIN clause.
            alias_expression = next(
                (
                    node.args.get("alias")
                    for node in statement.find_all(exp.Table)
                    if node.args.get("alias") is not None
                    and node.args["alias"].name.lower() == qualifier_key
                ),
                None,
            )
            if alias_expression is not None:
                column.set("table", exp.to_identifier(alias_expression.name, quoted=True))

        # A qualified column may use a physical table name instead of an alias
        # (for example Product.ProductID). PostgreSQL quoted mixed-case table
        # names must be canonicalized in the qualifier as well as the column.
        # Real SQL aliases are intentionally left untouched because aliases are
        # query-local identifiers, not physical catalog identifiers.
        if qualifier and qualifier_key not in query_aliases:
            exact_table_name = physical_table_names.get(qualifier.lower())
            if exact_table_name:
                # The FROM relation is emitted as "schema"."table". PostgreSQL
                # does not allow a three-part "schema"."table"."column"
                # reference. With no explicit alias, emit the now-unambiguous
                # quoted column without a table qualifier.
                column.set("table", None)

    return statement.sql(dialect=target)
