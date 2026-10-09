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


@dataclass(frozen=True)
class GovernedMetricSource:
    """Trusted physical source mapping for one published metric."""
    entity_id: int
    schema_name: str
    table_name: str
    column_name: str


def compile_analytical_aggregation(
    physical_plan: UnifiedPhysicalAnalyticalPlan,
    *,
    metric_source: GovernedMetricSource,
) -> CompiledAnalyticalQuery:
    """Compile only a single-table, single-metric approved aggregation.

    The metric source must be resolved from trusted catalog metadata, not
    request input. Calculated expressions and unverified joins are rejected.
    This compiler does not authorize execution or enforce dataset policies.
    """
    if not isinstance(physical_plan, UnifiedPhysicalAnalyticalPlan):
        raise ValueError("Unified governed physical plan is required")
    if not isinstance(metric_source, GovernedMetricSource):
        raise ValueError("Governed metric source is required")
    plan = physical_plan.bound_plan.plan
    if len(plan.sources) != 1 or len(plan.steps) != 1:
        raise ValueError("Unsupported analytical aggregation graph")
    step = plan.steps[0]
    if step.operation is not AnalyticalOperation.AGGREGATE or step.inputs != plan.sources:
        raise ValueError("Unsupported analytical aggregation operation")
    if set(step.parameters) != {"metric"}:
        raise ValueError("Aggregation requires only one governed metric")
    if len(physical_plan.metrics) != 1 or physical_plan.dimensions or physical_plan.time_dimensions:
        raise ValueError("Aggregation requires exactly one approved metric")
    if len(physical_plan.bound_plan.references) != 1:
        raise ValueError("Aggregation requires one governed reference")
    reference = physical_plan.bound_plan.references[0]
    metric = physical_plan.metrics[0]
    if (reference.kind, reference.step_id, reference.parameter) != ("metric", step.id, "metric"):
        raise ValueError("Metric reference does not match aggregation")
    if (metric.step_id, metric.parameter, metric.semantic_name) != (
        step.id, "metric", reference.name
    ):
        raise ValueError("Metric binding does not match aggregation")
    if type(metric.entity_id) is not int or metric.entity_id <= 0 or (
        type(metric_source.entity_id) is not int or metric.entity_id != metric_source.entity_id
    ):
        raise ValueError("Metric source entity mismatch")
    if metric.calculation_expression is not None:
        raise ValueError("Calculated metric expressions are not supported")
    if not isinstance(metric.attribute_name, str) or metric.attribute_name != metric_source.column_name:
        raise ValueError("Metric source column mismatch")
    if metric.aggregation not in ("SUM", "COUNT", "AVG", "MIN", "MAX"):
        raise ValueError("Unsupported governed aggregation function")
    schema = _quote_identifier(metric_source.schema_name)
    table = _quote_identifier(metric_source.table_name)
    column = _quote_identifier(metric_source.column_name)
    return CompiledAnalyticalQuery(
        sql=f'SELECT {metric.aggregation}({column}) AS "value" FROM {schema}.{table}'
    )
