"""Fail-closed plan-to-SQL verification for supported governed analytical plans.

This first checkpoint uses deterministic recompilation as its authority. It
does not claim to be independent AST verification; that is a subsequent stage.
"""
from dataclasses import dataclass

from datapilot.application.services.analytical_plan import AnalyticalOperation

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
        # Derive expected roles from the governed physical plan, not the SQL compiler.
        plan = physical_plan.bound_plan.plan
        group_step = next(s for s in plan.steps if s.operation is AnalyticalOperation.GROUP)
        aggregate_step = next(s for s in plan.steps if s.operation is AnalyticalOperation.AGGREGATE)
        sort_step = next(s for s in plan.steps if s.operation is AnalyticalOperation.SORT)
        limit_step = next(s for s in plan.steps if s.operation is AnalyticalOperation.LIMIT)
        dimension = next(d for d in physical_plan.dimensions if d.step_id == group_step.id)
        metric = next(m for m in physical_plan.metrics if m.step_id == aggregate_step.id)
        group_expr = parsed.args["group"].expressions[0]
        if not isinstance(group_expr, exp.Column) or group_expr.name != dimension.column_name:
            return AnalyticalSQLVerification(False, "Grouping dimension differs from governed binding")
        projections = parsed.expressions
        if (
            not isinstance(projections[0], exp.Alias)
            or not isinstance(projections[0].this, exp.Column)
            or projections[0].this.name != dimension.column_name
            or projections[0].alias != "dimension"
            or not isinstance(projections[1], exp.Alias)
            or projections[1].alias != "value"
        ):
            return AnalyticalSQLVerification(False, "Projection differs from governed dimension")
        aggregate_expr = projections[1].this
        if (
            not isinstance(aggregate_expr, exp.AggFunc)
            or aggregate_expr.key.upper() != metric.aggregation.upper()
            or not isinstance(aggregate_expr.this, exp.Column)
            or aggregate_expr.this.name != metric_source.column_name
        ):
            return AnalyticalSQLVerification(False, "Aggregate differs from governed metric")
        ordering = parsed.args["order"].expressions
        sort_role = "value" if "metric" in sort_step.parameters else "dimension"
        if (
            len(ordering) != 1
            or not isinstance(ordering[0].this, exp.Column)
            or ordering[0].this.name != sort_role
            or ordering[0].args.get("desc") != (sort_step.parameters["direction"] == "DESC")
        ):
            return AnalyticalSQLVerification(False, "Sort differs from governed plan")
        limit_expr = parsed.args["limit"].expression
        if not isinstance(limit_expr, exp.Literal) or int(limit_expr.this) != limit_step.parameters["count"]:
            return AnalyticalSQLVerification(False, "Limit differs from governed plan")
        filters = [s for s in plan.steps if s.operation is AnalyticalOperation.FILTER]
        where = parsed.args.get("where")
        if bool(filters) != bool(where):
            return AnalyticalSQLVerification(False, "Filter presence differs from governed plan")
        if filters:
            def split_and(node):
                if isinstance(node, exp.And):
                    return split_and(node.left) + split_and(node.right)
                return [node]
            predicates = split_and(where.this)
            if len(predicates) != len(filters):
                return AnalyticalSQLVerification(False, "Filter count differs from governed plan")
            for step, predicate in zip(filters, predicates):
                mapping = next(d for d in physical_plan.dimensions if d.step_id == step.id)
                op = step.parameters["operator"]
                if op == "EQ":
                    valid = isinstance(predicate, exp.EQ) and isinstance(predicate.left, exp.Column) and predicate.left.name == mapping.column_name
                elif op == "IN":
                    valid = isinstance(predicate, exp.In) and isinstance(predicate.this, exp.Column) and predicate.this.name == mapping.column_name and len(predicate.expressions) == len(step.parameters["values"])
                else:
                    valid = False
                if not valid:
                    return AnalyticalSQLVerification(False, "Filter operator or dimension differs from governed plan")
        thresholds = [s for s in plan.steps if s.operation is AnalyticalOperation.THRESHOLD]
        having = parsed.args.get("having")
        if bool(thresholds) != bool(having):
            return AnalyticalSQLVerification(False, "Threshold presence differs from governed plan")
        if thresholds:
            operators = {"GT": exp.GT, "GTE": exp.GTE, "LT": exp.LT, "LTE": exp.LTE, "EQ": exp.EQ}
            threshold = thresholds[0]
            predicate = having.this
            if (
                len(thresholds) != 1
                or not isinstance(predicate, operators[threshold.parameters["operator"]])
                or predicate.left.sql(dialect="postgres") != aggregate_expr.sql(dialect="postgres")
            ):
                return AnalyticalSQLVerification(False, "Threshold differs from governed metric")
        # AST-level parameter count guards against malformed placeholder syntax.
        if len(list(parsed.find_all(exp.Literal))) < len(compiled.parameters):
            return AnalyticalSQLVerification(False, "Insufficient SQL parameter expressions")
    except (sqlglot.errors.ParseError, ValueError, TypeError, AttributeError):
        return AnalyticalSQLVerification(False, "SQL AST parsing failed")
    return AnalyticalSQLVerification(True, "SQL matches governed compilation and AST structure")
