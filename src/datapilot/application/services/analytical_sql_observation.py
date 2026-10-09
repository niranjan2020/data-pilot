"""Offline structural SQL observation. Not semantic correctness evidence."""
from __future__ import annotations
from dataclasses import dataclass
from sqlglot import exp, parse
from datapilot.application.services.analytical_legacy_observation import DryRunObservation
from datapilot.application.services.analytical_plan import AnalyticalOperation as Op

@dataclass(frozen=True)
class AnalyticalSQLObservation:
    case_id: str
    operations: tuple[Op, ...]
    sources: tuple[str, ...]
    supported: bool
    reasons: tuple[str, ...]
    semantic_verified: bool = False

def inspect_analytical_sql_observation(
    observation: DryRunObservation, *, dialect: str = "postgres"
) -> AnalyticalSQLObservation:
    if not isinstance(observation, DryRunObservation):
        raise ValueError("A typed dry-run observation is required")
    if not isinstance(dialect, str) or not dialect.strip():
        raise ValueError("SQL dialect is required")
    if observation.typed_plan_available:
        raise ValueError("Use governed typed-plan evaluation")
    if observation.status != "dry_run" or not observation.sql or not observation.sql.strip():
        return AnalyticalSQLObservation(observation.case_id, (), (), False, ("sql_not_available",))
    try:
        statements = parse(observation.sql, read=dialect)
    except Exception:
        return AnalyticalSQLObservation(observation.case_id, (), (), False, ("sql_parse_failed",))
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        return AnalyticalSQLObservation(observation.case_id, (), (), False, ("unsupported_statement",))
    statement = statements[0]
    unsupported = (exp.Subquery, exp.Union, exp.Intersect, exp.Except,
                   exp.With, exp.Window, exp.Join, exp.Having, exp.Qualify)
    if any(isinstance(node, unsupported) for node in statement.walk()):
        return AnalyticalSQLObservation(observation.case_id, (), (), False, ("complex_sql_not_supported",))
    tables = list(statement.find_all(exp.Table))
    if len(tables) != 1 or not tables[0].name or statement.args.get("from_") is None:
        return AnalyticalSQLObservation(observation.case_id, (), (), False, ("source_not_unique",))
    if statement.find(exp.Star) is not None:
        return AnalyticalSQLObservation(observation.case_id, (), (), False, ("wildcard_projection",))
    table = tables[0]
    sources = (f"{table.db}.{table.name}" if table.db else table.name,)
    operations: list[Op] = []
    if statement.args.get("where") is not None:
        operations.append(Op.FILTER)
    if statement.args.get("group") is not None:
        operations.append(Op.GROUP)
    if any(isinstance(node, exp.AggFunc) for node in statement.walk()):
        operations.append(Op.AGGREGATE)
    if statement.args.get("order") is not None:
        operations.append(Op.SORT)
    if statement.args.get("limit") is not None:
        operations.append(Op.LIMIT)
    if statement.args.get("offset") is not None or statement.args.get("distinct") is not None:
        return AnalyticalSQLObservation(observation.case_id, tuple(operations), sources,
                                        False, ("unsupported_sql_modifier",))
    return AnalyticalSQLObservation(observation.case_id, tuple(operations), sources,
                                    True, ("semantic_binding_not_verified",))
