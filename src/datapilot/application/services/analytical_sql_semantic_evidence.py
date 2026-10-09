"""Independent offline SQL semantic evidence. No database execution.

Bindings must be supplied by an independently reviewed published catalog.
Only exact column and aggregate-expression matching is supported.
"""
from dataclasses import dataclass
from sqlglot import exp, parse_one
from datapilot.application.services.analytical_evaluation import AnalyticalEvaluationCase

@dataclass(frozen=True)
class SQLSemanticEvidence:
    case_id: str
    verified: bool
    failures: tuple[str, ...]

def verify_sql_semantics(
    case: AnalyticalEvaluationCase, sql: str, *,
    dimension_columns: dict[str, str],
    metric_expressions: dict[str, str],
    dialect: str = "postgres",
) -> SQLSemanticEvidence:
    if not isinstance(case, AnalyticalEvaluationCase):
        raise ValueError("Typed expectation required")
    if not isinstance(sql, str) or not sql.strip():
        return SQLSemanticEvidence(case.case_id, False, ("sql_missing",))
    if not isinstance(dimension_columns, dict) or not isinstance(metric_expressions, dict):
        raise ValueError("Trusted semantic bindings required")
    failures = []
    try:
        tree = parse_one(sql, read=dialect)
    except Exception:
        return SQLSemanticEvidence(case.case_id, False, ("sql_parse_failed",))
    if not isinstance(tree, exp.Select):
        return SQLSemanticEvidence(case.case_id, False, ("unsupported_statement",))
    if any(isinstance(node, (exp.Join, exp.Subquery, exp.Union, exp.With, exp.Window, exp.Having)) for node in tree.walk()):
        return SQLSemanticEvidence(case.case_id, False, ("complex_sql_requires_governed_plan",))
    group = tree.args.get("group")
    grouped = set()
    if group is not None:
        grouped = {e.sql(dialect=dialect).casefold() for e in group.expressions}
    for name in dict.fromkeys(case.expected_dimensions):
        physical = dimension_columns.get(name)
        if not isinstance(physical, str) or not physical.strip():
            failures.append("unpublished_dimension:" + name)
        elif physical.casefold() not in grouped:
            failures.append("grouping_dimension_mismatch:" + name)
    projections = {node.sql(dialect=dialect).casefold() for node in tree.expressions}
    for name in dict.fromkeys(case.expected_metrics):
        physical = metric_expressions.get(name)
        if not isinstance(physical, str) or not physical.strip():
            failures.append("unpublished_metric:" + name)
        elif physical.casefold() not in projections:
            failures.append("metric_expression_mismatch:" + name)
    # No claim about predicate literals, time grain, fanout, or result rows.
    if tree.args.get("where") is not None:
        failures.append("filter_values_not_verified")
    if tree.args.get("limit") is not None:
        failures.append("limit_value_not_verified")
    if tree.args.get("order") is not None:
        failures.append("sort_semantics_not_verified")
    if not failures:
        failures.append("result_correctness_not_verified")
    return SQLSemanticEvidence(case.case_id, False, tuple(failures))
