"""Attach approved metric and time-role mappings to bound analytical plans.

The caller supplies only records loaded from the authoritative semantic
catalog after datasource-scoped publication verification. No SQL is emitted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from datapilot.application.services.analytical_plan_binding import BoundAnalyticalPlan


@dataclass(frozen=True)
class PhysicalMetricBinding:
    step_id: str
    parameter: str
    semantic_name: str
    entity_id: int
    attribute_name: str | None
    aggregation: str
    calculation_expression: str | None


@dataclass(frozen=True)
class PhysicalTimeBinding:
    step_id: str
    parameter: str
    semantic_name: str
    entity_id: int
    column_name: str
    role: str
    grain: str


@dataclass(frozen=True)
class PhysicalMeasureTimePlan:
    bound_plan: BoundAnalyticalPlan
    metrics: tuple[PhysicalMetricBinding, ...]
    time_dimensions: tuple[PhysicalTimeBinding, ...]


def attach_physical_measures_and_time(
    bound_plan: BoundAnalyticalPlan,
    *,
    published_metrics: tuple[Mapping[str, Any], ...],
    published_time_dimensions: tuple[Mapping[str, Any], ...],
) -> PhysicalMeasureTimePlan:
    """Fail closed for missing, ambiguous, or incomplete approved mappings.

    Expressions are carried as opaque catalog data. SQL compilation must
    parse and validate them before use; never concatenate them into SQL.
    """
    if not isinstance(bound_plan, BoundAnalyticalPlan):
        raise ValueError("A governed bound analytical plan is required")

    def index(records, kind):
        result: dict[str, Mapping[str, Any]] = {}
        for record in records:
            if not isinstance(record, Mapping):
                raise ValueError(f"Invalid {kind} record")
            name = record.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"Unnamed {kind} record")
            key = name.casefold()
            if key in result:
                raise ValueError(f"Ambiguous {kind} name")
            result[key] = record
        return result

    metrics = index(published_metrics, "metric")
    times = index(published_time_dimensions, "time dimension")
    metric_bindings = []
    time_bindings = []
    for reference in bound_plan.references:
        if reference.kind not in ("metric", "time_dimension"):
            continue
        records = metrics if reference.kind == "metric" else times
        record = records.get(reference.name.casefold())
        if record is None:
            raise ValueError(f"Missing approved {reference.kind} mapping")
        entity_id = record.get("entity_id")
        if type(entity_id) is not int or entity_id <= 0:
            raise ValueError("Invalid governed entity identifier")
        if reference.kind == "metric":
            aggregation = record.get("aggregation")
            if not isinstance(aggregation, str) or not aggregation.strip():
                raise ValueError("Incomplete approved metric mapping")
            attribute_name = record.get("attribute_name")
            expression = record.get("calculation_expression")
            if attribute_name is not None and not isinstance(attribute_name, str):
                raise ValueError("Invalid approved metric attribute")
            if expression is not None and not isinstance(expression, str):
                raise ValueError("Invalid approved metric expression")
            if not (attribute_name and attribute_name.strip()) and not (expression and expression.strip()):
                raise ValueError("Metric requires a governed attribute or expression")
            metric_bindings.append(PhysicalMetricBinding(
                step_id=reference.step_id, parameter=reference.parameter,
                semantic_name=reference.name, entity_id=entity_id,
                attribute_name=attribute_name, aggregation=aggregation,
                calculation_expression=expression,
            ))
        else:
            column, role, grain = (
                record.get("column_name"), record.get("role"), record.get("grain"),
            )
            if not all(isinstance(x, str) and x.strip() for x in (column, role, grain)):
                raise ValueError("Incomplete approved time dimension mapping")
            time_bindings.append(PhysicalTimeBinding(
                step_id=reference.step_id, parameter=reference.parameter,
                semantic_name=reference.name, entity_id=entity_id,
                column_name=column, role=role, grain=grain,
            ))
    return PhysicalMeasureTimePlan(
        bound_plan=bound_plan,
        metrics=tuple(metric_bindings),
        time_dimensions=tuple(time_bindings),
    )
