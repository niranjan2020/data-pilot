"""SQLGlot-based AST safety validator for Data Pilot."""

from __future__ import annotations

from typing import Optional

import sqlglot
from sqlglot import exp

from datapilot.domain.models import SQLValidationResult
from datapilot.infrastructure.sql.dialects import sqlglot_dialect


class SQLGlotValidator:
    """Validate SQL structurally before it reaches a database provider."""

    _MUTATING = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Create,
        exp.Drop,
        exp.Alter,
        exp.Merge,
        exp.TruncateTable,
        exp.Grant,
        exp.Revoke,
        exp.Command,
    )

    async def validate(
        self,
        sql: str,
        dialect: Optional[str] = None,
        enforce_read_only: bool = True,
    ) -> SQLValidationResult:
        """Validate one SQL statement without executing it."""
        return self._validate(sql, dialect=dialect, enforce_read_only=enforce_read_only)

    @classmethod
    def _validate(
        cls,
        sql: str,
        dialect: Optional[str] = None,
        enforce_read_only: bool = True,
    ) -> SQLValidationResult:
        if not isinstance(sql, str) or not sql.strip():
            return SQLValidationResult(
                is_valid=False,
                is_read_only=False,
                errors=["SQL query must be a non-empty string"],
            )

        target_dialect = sqlglot_dialect(dialect)
        try:
            statements = sqlglot.parse(sql, read=target_dialect)
        except sqlglot.errors.ParseError as exc:
            return SQLValidationResult(
                is_valid=False,
                is_read_only=False,
                errors=[f"SQL parsing failed: {exc}"],
            )

        if len(statements) != 1:
            return SQLValidationResult(
                is_valid=False,
                is_read_only=False,
                errors=["Multiple SQL statements are not allowed"],
            )

        statement = statements[0]
        is_read_only = cls._is_read_only(statement)
        errors: list[str] = []
        warnings: list[str] = []

        if enforce_read_only and not is_read_only:
            errors.append("Only read-only SELECT queries are allowed")

        if isinstance(statement, exp.Select) and statement.args.get("limit") is None:
            warnings.append("Query has no LIMIT clause")

        affected_tables = sorted(
            {table.sql(dialect=target_dialect) for table in statement.find_all(exp.Table)}
        )

        return SQLValidationResult(
            is_valid=not errors,
            is_read_only=is_read_only,
            errors=errors,
            warnings=warnings,
            sanitized_sql=statement.sql(dialect=target_dialect),
            affected_tables=affected_tables,
        )

    @classmethod
    def _is_read_only(cls, statement: exp.Expression) -> bool:
        """Reject mutating nodes anywhere in the AST, including CTEs."""
        if not isinstance(statement, (exp.Select, exp.Union, exp.Except, exp.Intersect)):
            return False

        return not any(statement.find(node_type) for node_type in cls._MUTATING)
