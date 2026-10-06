"""SQL AST-based query resource policy enforcement."""

from __future__ import annotations

from typing import Optional

import sqlglot
from sqlglot import exp

from datapilot.domain.policies import QueryExecutionPolicy, QueryPolicyResult
from datapilot.infrastructure.sql.dialects import sqlglot_dialect


class SQLQueryPolicyEnforcer:
    """Apply conservative query resource limits using SQL AST inspection."""

    def enforce(
        self,
        sql: str,
        dialect: Optional[str],
        policy: QueryExecutionPolicy,
    ) -> QueryPolicyResult:
        if not isinstance(sql, str) or not sql.strip():
            return QueryPolicyResult(
                is_allowed=False,
                sql=sql or "",
                errors=["SQL query must be non-empty"],
            )

        if len(sql) > policy.max_query_length:
            return QueryPolicyResult(
                is_allowed=False,
                sql=sql,
                errors=[
                    f"SQL query exceeds maximum length of {policy.max_query_length} characters"
                ],
            )

        target = sqlglot_dialect(dialect)
        try:
            statements = sqlglot.parse(sql, read=target)
        except (sqlglot.errors.ParseError, ValueError) as exc:
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
                errors=[
                    "Only read-only query expressions are supported by the execution policy"
                ],
            )

        limit = statement.args.get("limit")
        warnings: list[str] = []

        if limit is not None:
            requested = self._numeric_limit(limit)
            if requested is None:
                return QueryPolicyResult(
                    is_allowed=False,
                    sql=sql,
                    errors=[
                        "LIMIT must be a non-negative integer literal so the execution "
                        "policy can deterministically bound result rows"
                    ],
                )
            if requested > policy.max_limit:
                statement = self._replace_limit(statement, policy.max_limit)
                warnings.append(
                    f"Reduced requested LIMIT {requested} to policy maximum {policy.max_limit}."
                )
        elif self._requires_result_limit(statement, policy):
            result_limit = min(policy.default_limit, policy.max_limit, policy.max_result_rows)
            statement = self._apply_limit(statement, result_limit)
            warnings.append(
                f"Applied resource-policy LIMIT {result_limit} to row-producing query."
            )

        return QueryPolicyResult(
            is_allowed=True,
            sql=statement.sql(dialect=target),
            warnings=warnings,
        )

    @classmethod
    def _requires_result_limit(
        cls,
        statement: exp.Expression,
        policy: QueryExecutionPolicy,
    ) -> bool:
        """Return whether the top-level query can produce an unbounded row set."""
        if isinstance(statement, (exp.Union, exp.Except, exp.Intersect)):
            return True

        if not isinstance(statement, exp.Select):
            return True

        if cls._is_scalar_aggregate(statement):
            return False

        # A grouped aggregate is row-producing even though it contains aggregate
        # functions. DISTINCT and ordinary projections are row-producing as well.
        if statement.args.get("group") is not None:
            return True
        if statement.args.get("distinct") is not None:
            return True

        aggregate = cls._contains_aggregate(statement)
        if aggregate:
            # Non-grouped aggregate projections are normally scalar. If the query
            # also projects a non-aggregate expression, fail safely by bounding it.
            return not cls._select_projection_is_aggregate_only(statement)

        return policy.require_limit_for_non_aggregate

    @staticmethod
    def _contains_aggregate(statement: exp.Expression) -> bool:
        return statement.find(exp.AggFunc) is not None

    @classmethod
    def _is_scalar_aggregate(cls, statement: exp.Select) -> bool:
        return (
            statement.args.get("group") is None
            and cls._contains_aggregate(statement)
            and cls._select_projection_is_aggregate_only(statement)
        )

    @staticmethod
    def _select_projection_is_aggregate_only(statement: exp.Select) -> bool:
        expressions = list(statement.expressions)
        if not expressions:
            return False

        for projection in expressions:
            value = projection.this if isinstance(projection, exp.Alias) else projection
            if value.find(exp.AggFunc) is None:
                return False
        return True

    @staticmethod
    def _numeric_limit(limit: exp.Expression) -> Optional[int]:
        expression = limit.args.get("expression")
        if isinstance(expression, exp.Literal) and expression.is_int:
            value = int(expression.this)
            return value if value >= 0 else None
        return None

    @staticmethod
    def _apply_limit(statement: exp.Expression, value: int) -> exp.Expression:
        return statement.limit(value)

    @staticmethod
    def _replace_limit(statement: exp.Expression, value: int) -> exp.Expression:
        return statement.limit(value)
