"""Attach trusted physical dimension mappings to an already governed plan.

This intermediate representation is a prerequisite for deterministic SQL
compilation. It never accepts physical identifiers from plan parameters.
"""
from __future__ import annotations

from dataclasses import dataclass

from datapilot.application.services.analytical_dimensions import (
    AnalyticalDimension, resolve_analytical_dimension,
)
from datapilot.application.services.analytical_plan_binding import (
    BoundAnalyticalPlan,
)


@dataclass(frozen=True)
class PhysicalDimensionBinding:
    step_id: str
    parameter: str
    semantic_name: str
    entity_id: int
    schema_name: str
    table_name: str
    column_name: str


@dataclass(frozen=True)
class PhysicalAnalyticalPlan:
    bound_plan: BoundAnalyticalPlan
    dimensions: tuple[PhysicalDimensionBinding, ...]


def attach_physical_dimensions(
    bound_plan: BoundAnalyticalPlan,
    *,
    published_dimensions: tuple[AnalyticalDimension, ...],
) -> PhysicalAnalyticalPlan:
    """Bind dimensions to authoritative metadata without generating SQL.

    All dimension references must resolve uniquely against the exact
    published attribute set. Unpublished names and stale mappings fail.
    """
    if not isinstance(bound_plan, BoundAnalyticalPlan):
        raise ValueError("A governed bound analytical plan is required")
    bindings: list[PhysicalDimensionBinding] = []
    for reference in bound_plan.references:
        if reference.kind != "dimension":
            continue
        dimension = resolve_analytical_dimension(
            published_dimensions, reference.name,
        )
        bindings.append(PhysicalDimensionBinding(
            step_id=reference.step_id,
            parameter=reference.parameter,
            semantic_name=f"{dimension.entity_name}.{dimension.name}",
            entity_id=dimension.entity_id,
            schema_name=dimension.schema_name,
            table_name=dimension.table_name,
            column_name=dimension.column_name,
        ))
    return PhysicalAnalyticalPlan(
        bound_plan=bound_plan, dimensions=tuple(bindings),
    )
