"""Unified physical bindings for deterministic analytical compilation.

All references originate from an already governed plan. Metadata inputs
must be authoritative, published catalog snapshots; never request payloads.
No SQL is generated or executed by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_measure_time_binding import (
    PhysicalMetricBinding,
    PhysicalTimeBinding,
    attach_physical_measures_and_time,
)
from datapilot.application.services.analytical_physical_binding import (
    PhysicalDimensionBinding,
    attach_physical_dimensions,
)
from datapilot.application.services.analytical_plan_binding import BoundAnalyticalPlan


@dataclass(frozen=True)
class UnifiedPhysicalAnalyticalPlan:
    bound_plan: BoundAnalyticalPlan
    dimensions: tuple[PhysicalDimensionBinding, ...]
    metrics: tuple[PhysicalMetricBinding, ...]
    time_dimensions: tuple[PhysicalTimeBinding, ...]

    def __post_init__(self) -> None:
        expected = {
            (reference.step_id, reference.parameter, reference.kind)
            for reference in self.bound_plan.references
        }
        actual = [
            (item.step_id, item.parameter, "dimension")
            for item in self.dimensions
        ] + [
            (item.step_id, item.parameter, "metric")
            for item in self.metrics
        ] + [
            (item.step_id, item.parameter, "time_dimension")
            for item in self.time_dimensions
        ]
        if len(actual) != len(expected) or set(actual) != expected:
            raise ValueError("Incomplete or duplicate physical analytical bindings")


def unify_physical_analytical_plan(
    bound_plan: BoundAnalyticalPlan,
    *,
    published_dimensions: tuple[AnalyticalDimension, ...],
    published_metrics: tuple[Mapping[str, Any], ...],
    published_time_dimensions: tuple[Mapping[str, Any], ...],
) -> UnifiedPhysicalAnalyticalPlan:
    """Require complete physical mappings for every governed plan reference."""
    dimensions = attach_physical_dimensions(
        bound_plan, published_dimensions=published_dimensions,
    )
    measures = attach_physical_measures_and_time(
        bound_plan, published_metrics=published_metrics,
        published_time_dimensions=published_time_dimensions,
    )
    return UnifiedPhysicalAnalyticalPlan(
        bound_plan=bound_plan,
        dimensions=dimensions.dimensions,
        metrics=measures.metrics,
        time_dimensions=measures.time_dimensions,
    )
