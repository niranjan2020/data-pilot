"""Fail-closed plan-to-SQL verification for supported governed analytical plans.

This first checkpoint uses deterministic recompilation as its authority. It
does not claim to be independent AST verification; that is a subsequent stage.
"""
from dataclasses import dataclass

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
    return AnalyticalSQLVerification(True, "SQL matches deterministic governed compilation")
