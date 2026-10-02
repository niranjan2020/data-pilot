"""SQL AST-based query resource policy enforcement."""

from __future__ import annotations

from typing import Optional

import sqlglot
from sqlglot import exp

from datapilot.domain.policies import QueryExecutionPolicy, QueryPolicyResult


class SQLQueryPolicyEnforcer:
    """Apply conservative query resource limits using SQL AST inspection."""

    def enforce(
        self,
        sql: str,
        dialect: Optional[str],
        policy: QueryExecutionPolicy,
    ) -> QueryPolicyResult:
        if not isinstance(sql, str) or not sql.strip():
            return QueryPolicyResult(is_allowed=False, sql=sql or "", errors=["SQL query must be non-empty"])

        if len(sql) > policy.max_query_length:
            return QueryPolicyResult(
                is_allowed=False,
                sql=sql,
                errors=[f"SQL query exceeds maximum length of {policy.max_query_length} characters"],
            )

        target = dialect or "postgres"
        try:
            statements = sqlglot.parse(sql, read=target)
        except sqlglot.errors.ParseError as exc:
            return QueryPolicyResult(
                is_allowed=False,
                sql=sql,
                errors=[f"SQL parsing failed during policy enforcement: {exc}"],
            )

        if len(statements) != 1:
            return QueryPolicyResult(
                is_allowed=False,
                sql=sql,
                errors=["Multiple SQL statements are not allowed"],
            )

        statement = statements[0]
        if not isinstance(statement, (exp.Select, exp.Union, exp.Except, exp.Intersect)):
            return QueryPolicyResult(
                is_allowed=False,
                sql=sql,
                errors=["Only read-only query expressions are supported by the execution policy"],
            )

        limit = statement.args.get("limit")
        aggregate = self._contains_aggregate(statement)

        warnings: list[str] = []
        if limit is None and policy.require_limit_for_non_aggregate and not aggregate:
            statement = self._apply_limit(statement, policy.default_limit)
            warnings.append(f"Applied default LIMIT {policy.default_limit} to non-aggregate query.")
        elif limit is not None:
            requested = self._numeric_limit(limit)
            if requested is not None and requested > policy.max_limit:
                statement = self._replace_limit(statement, policy.max_limit)
                warnings.append(
                    f"Reduced requested LIMIT {requested} to policy maximum {policy.max_limit}."
                )

        return QueryPolicyResult(
            is_allowed=True,
            sql=statement.sql(dialect=target),
            warnings=warnings,
        )

    @staticmethod
    def _contains_aggregate(statement: exp.Expression) -> bool:
        return any(statement.find(exp.AggFunc) for _ in [0])

    @staticmethod
    def _numeric_limit(limit: exp.Expression) -> Optional[int]:
        expression = limit.args.get("expression")
        if isinstance(expression, exp.Literal) and expression.is_int:
            return int(expression.this)
        return None

    @staticmethod
    def _apply_limit(statement: exp.Expression, value: int) -> exp.Expression:
        return statement.limit(value)

    @staticmethod
    def _replace_limit(statement: exp.Expression, value: int) -> exp.Expression:
        return statement.limit(value)
