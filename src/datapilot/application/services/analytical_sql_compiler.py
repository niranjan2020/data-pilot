"""Conservative PostgreSQL projection compiler for governed analytical plans.

Only a single-source, single-step dimension projection is supported.
All other operation graphs fail closed. No user-supplied SQL fragments are
accepted, and compilation does not execute queries.
"""
from __future__ import annotations

from dataclasses import dataclass

from datapilot.application.services.analytical_plan import AnalyticalOperation
from datapilot.application.services.unified_analytical_binding import (
    UnifiedPhysicalAnalyticalPlan,
)


@dataclass(frozen=True)
class CompiledAnalyticalQuery:
    sql: str
    dialect: str = "postgres"


def _quote_identifier(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("Invalid governed SQL identifier")
    return '"' + value.replace('"', '""') + '"'


def compile_analytical_projection(
    physical_plan: UnifiedPhysicalAnalyticalPlan,
) -> CompiledAnalyticalQuery:
    """Compile a single published dimension projection, or reject the plan.

    No JOIN, WHERE, aggregation, expression or user-supplied physical
    identifiers are supported. This is not an execution authorization gate.
    """
    if not isinstance(physical_plan, UnifiedPhysicalAnalyticalPlan):
        raise ValueError("Unified governed physical plan is required")
    bound = physical_plan.bound_plan
    plan = bound.plan
    if len(plan.sources) != 1 or len(plan.steps) != 1:
        raise ValueError("Unsupported analytical projection graph")
    step = plan.steps[0]
    if step.operation is not AnalyticalOperation.PROJECT or step.inputs != plan.sources:
        raise ValueError("Unsupported analytical projection operation")
    if set(step.parameters) != {"dimension"}:
        raise ValueError("Projection requires only one governed dimension")
    if len(physical_plan.dimensions) != 1 or physical_plan.metrics or physical_plan.time_dimensions:
        raise ValueError("Projection requires exactly one approved physical dimension")
    mapping = physical_plan.dimensions[0]
    if mapping.step_id != step.id or mapping.parameter != "dimension":
        raise ValueError("Physical dimension does not match projection step")
    if len(bound.references) != 1 or bound.references[0].kind != "dimension":
        raise ValueError("Projection requires a governed dimension reference")
    if not all(
        isinstance(value, str) and value and "\x00" not in value
        for value in (mapping.schema_name, mapping.table_name, mapping.column_name)
    ):
        raise ValueError("Incomplete physical dimension mapping")
    column = _quote_identifier(mapping.column_name)
    schema = _quote_identifier(mapping.schema_name)
    table = _quote_identifier(mapping.table_name)
    return CompiledAnalyticalQuery(
        sql=f"SELECT {column} FROM {schema}.{table}"
    )
