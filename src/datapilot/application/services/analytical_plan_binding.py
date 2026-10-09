"""Conservative semantic binding for composable analytical plans.

Only references with explicit governed parameter roles are resolved. This
module does not generate SQL or infer semantic definitions from column names.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datapilot.application.services.analytical_plan import AnalyticalOperation, AnalyticalPlan


@dataclass(frozen=True)
class BoundReference:
    step_id: str
    parameter: str
    kind: str
    name: str


@dataclass(frozen=True)
class BoundAnalyticalPlan:
    plan: AnalyticalPlan
    references: tuple[BoundReference, ...]


# A role's semantic kind is determined by the operation and parameter,
# never by a user-controlled field claiming to be an approved metric.
REFERENCE_ROLES: dict[AnalyticalOperation, dict[str, str]] = {
    AnalyticalOperation.AGGREGATE: {"metric": "metric"},
    AnalyticalOperation.GROUP: {"dimension": "dimension"},
    AnalyticalOperation.RANK: {"metric": "metric", "dimension": "dimension", "partition_dimension": "dimension"},
    AnalyticalOperation.COMPARE: {"metric": "metric", "dimension": "dimension"},
    AnalyticalOperation.CONTRIBUTION: {"metric": "metric", "dimension": "dimension"},
    AnalyticalOperation.TIME_WINDOW: {"role": "time_dimension"},
    AnalyticalOperation.PROJECT: {"dimension": "dimension", "metric": "metric"},
    AnalyticalOperation.SORT: {"metric": "metric", "dimension": "dimension"},
    AnalyticalOperation.THRESHOLD: {"metric": "metric"},
}


def bind_analytical_plan(
    plan: AnalyticalPlan,
    *,
    approved_metrics: list[dict[str, Any]],
    approved_dimensions: list[dict[str, Any]],
    approved_time_dimensions: list[dict[str, Any]] | None = None,
) -> BoundAnalyticalPlan:
    """Fail closed for unknown or ambiguous governed semantic references.

    Catalog inputs must already be restricted to the approved/published
    datasource context by the caller. This function does not authenticate
    publication state or grant datasource access.
    """
    catalog = {
        "metric": approved_metrics,
        "dimension": approved_dimensions,
        "time_dimension": approved_time_dimensions or [],
    }
    indexes: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for kind, items in catalog.items():
        index: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            name = str(item.get("name") or "").strip()
            if not name:
                raise ValueError(f"Unnamed governed {kind}")
            index.setdefault(name.casefold(), []).append(item)
        indexes[kind] = index

    references: list[BoundReference] = []
    for step in plan.steps:
        for parameter, kind in REFERENCE_ROLES.get(step.operation, {}).items():
            if parameter not in step.parameters:
                continue
            value = step.parameters[parameter]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Invalid {kind} reference in {step.id}.{parameter}")
            matches = indexes[kind].get(value.strip().casefold(), [])
            if len(matches) != 1:
                raise ValueError(
                    f"Unresolved or ambiguous governed {kind}: {step.id}.{parameter}={value!r}"
                )
            references.append(BoundReference(step.id, parameter, kind, matches[0]["name"]))
    return BoundAnalyticalPlan(plan=plan, references=tuple(references))
