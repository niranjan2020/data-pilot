"""Trusted semantic requirements shared by SQL generation and verification.

The contract is assembled from resolved, published semantic metadata. It must
not be reconstructed from the generated SQL: that would allow the generator
to define its own acceptance criteria.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class SemanticIntentContract:
    metrics: tuple[dict[str, Any], ...]
    dimensions: tuple[str, ...]
    filters: tuple[dict[str, Any], ...]
    relationships: tuple[dict[str, Any], ...]
    time_plan: dict[str, Any] | None
    categorical_attribute: dict[str, Any] | None
    comparison_cohorts: tuple[dict[str, Any], ...] = ()
    aggregation_grain: tuple[str, ...] = ()

    @classmethod
    def from_governed_context(
        cls,
        context: Mapping[str, Any],
        *,
        grouping_columns: Sequence[str],
        required_filters: Sequence[dict[str, Any]],
        required_relationships: Sequence[dict[str, Any]],
        time_plan: dict[str, Any] | None,
        comparison_cohorts: Sequence[dict[str, Any]] = (),
        aggregation_grain: Sequence[str] | None = None,
    ) -> "SemanticIntentContract":
        return cls(
            metrics=tuple(deepcopy(context.get("metrics") or ())),
            dimensions=tuple(str(value) for value in grouping_columns),
            filters=tuple(deepcopy(required_filters)),
            relationships=tuple(deepcopy(required_relationships)),
            time_plan=deepcopy(time_plan),
            categorical_attribute=deepcopy(context.get("resolved_attribute_selection")),
            comparison_cohorts=tuple(deepcopy(comparison_cohorts)),
            aggregation_grain=tuple(str(v) for v in (aggregation_grain if aggregation_grain is not None else grouping_columns)),
        )

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe snapshot for LLM context and diagnostic traces."""
        return deepcopy({
            "metrics": list(self.metrics),
            "dimensions": list(self.dimensions),
            "filters": list(self.filters),
            "relationships": list(self.relationships),
            "time_plan": self.time_plan,
            "categorical_attribute": self.categorical_attribute,
            "comparison_cohorts": list(self.comparison_cohorts),
            "aggregation_grain": list(self.aggregation_grain),
        })
