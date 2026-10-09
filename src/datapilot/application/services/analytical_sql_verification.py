"""Fail-closed plan-to-SQL verification for supported governed analytical plans.

This first checkpoint uses deterministic recompilation as its authority. It
does not claim to be independent AST verification; that is a subsequent stage.
"""
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from datapilot.application.services.analytical_sql_compiler import (
    CompiledAnalyticalQuery,
    GovernedMetricSource,
    compile_governed_analytical_plan,
)
from datapilot.application.services.unified_analytical_binding import (
    UnifiedPhysicalAnalyticalPlan,
)


@dataclass(frozen=True)
class AnalyticalSQLVerification:
    verified: bool
    reason: str


def verify_governed_analytical_sql(
    physical_plan: UnifiedPhysicalAnalyticalPlan,
    compiled: CompiledAnalyticalQuery,
    *,
    metric_source: GovernedMetricSource,
    published_dimensions: tuple = (),
    max_rows: int = 1000,
    max_filters: int = 10,
) -> AnalyticalSQLVerification:
    """Verify exact compiler-authorized SQL, dialect, and bound parameters.

    Rejects altered projections, sources, joins, WHERE/HAVING predicates,
    grouping, sort, limit, parameter values, and unsupported plan shapes.
    No SQL is executed.
    """
    if not isinstance(compiled, CompiledAnalyticalQuery):
        return AnalyticalSQLVerification(False, "Invalid compiled SQL contract")
    try:
        expected = compile_governed_analytical_plan(
            physical_plan,
            metric_source=metric_source,
            published_dimensions=published_dimensions,
            max_rows=max_rows,
            max_filters=max_filters,
        )
    except (ValueError, TypeError, AttributeError, KeyError, StopIteration):
        return AnalyticalSQLVerification(False, "Plan cannot be compiled under governance")
    if compiled.dialect != expected.dialect:
        return AnalyticalSQLVerification(False, "SQL dialect differs from governed plan")
    if compiled.sql != expected.sql:
        return AnalyticalSQLVerification(False, "SQL differs from governed analytical plan")
    if type(compiled.parameters) is not tuple or compiled.parameters != expected.parameters:
        return AnalyticalSQLVerification(False, "Bound parameters differ from governed plan")
    if compiled.sql.count("%s") != len(compiled.parameters):
        return AnalyticalSQLVerification(False, "SQL placeholder count differs from parameters")
    try:
        # PostgreSQL DB-API placeholders are transport syntax, not SQL literals.
        # Replace only after exact deterministic SQL and parameter checks.
        parsed = sqlglot.parse_one(compiled.sql.replace("%s", "0"), read="postgres")
        if not isinstance(parsed, exp.Select):
            return AnalyticalSQLVerification(False, "Expected one SELECT statement")
        if any(
            isinstance(node, (exp.Join, exp.Subquery, exp.Union, exp.Intersect,
                              exp.Except, exp.CTE, exp.Window))
            for node in parsed.walk()
        ):
            return AnalyticalSQLVerification(False, "Unsupported SQL AST operation")
        tables = list(parsed.find_all(exp.Table))
        if len(tables) != 1:
            return AnalyticalSQLVerification(False, "Expected exactly one physical source")
        table = tables[0]
        if (
            table.name != metric_source.table_name
            or table.db != metric_source.schema_name
            or parsed.args.get("group") is None
            or parsed.args.get("order") is None
            or parsed.args.get("limit") is None
            or len(parsed.expressions) != 2
            or len(parsed.args["group"].expressions) != 1
        ):
            return AnalyticalSQLVerification(False, "SQL AST differs from governed query shape")
        if parsed.args.get("with") is not None or parsed.args.get("distinct") is not None:
            return AnalyticalSQLVerification(False, "Unexpected SQL AST clause")
        # AST-level parameter count guards against malformed placeholder syntax.
        if len(list(parsed.find_all(exp.Literal))) < len(compiled.parameters):
            return AnalyticalSQLVerification(False, "Insufficient SQL parameter expressions")
    except (sqlglot.errors.ParseError, ValueError, TypeError, AttributeError):
        return AnalyticalSQLVerification(False, "SQL AST parsing failed")
    return AnalyticalSQLVerification(True, "SQL matches governed compilation and AST structure")
