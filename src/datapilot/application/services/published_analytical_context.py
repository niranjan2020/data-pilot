"""Datasource-scoped semantic records for analytical plan binding.

Retrieval relevance is not publication authorization. Records must come from
an authoritative metadata provider, not an LLM or untrusted request.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datapilot.application.services.analytical_plan import AnalyticalPlan
from datapilot.application.services.analytical_plan_binding import (
    BoundAnalyticalPlan, bind_analytical_plan,
)


@dataclass(frozen=True)
class PublishedSemanticContext:
    datasource: str
    metrics: tuple[dict[str, Any], ...]
    dimensions: tuple[dict[str, Any], ...]
    time_dimensions: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.datasource, str) or not self.datasource.strip():
            raise ValueError("A datasource identifier is required")
        for kind, records in (
            ("metric", self.metrics),
            ("dimension", self.dimensions),
            ("time_dimension", self.time_dimensions),
        ):
            if not isinstance(records, tuple):
                raise ValueError(f"Governed {kind} records must be a tuple")
            for record in records:
                if not isinstance(record, dict):
                    raise ValueError(f"Invalid governed {kind} record")
                if str(record.get("datasource") or "").casefold() != self.datasource.casefold():
                    raise ValueError(f"Cross-datasource governed {kind} is forbidden")
                if record.get("published") is not True:
                    raise ValueError(f"Unpublished governed {kind} is forbidden")
                if not str(record.get("name") or "").strip():
                    raise ValueError(f"Unnamed governed {kind} is forbidden")


def bind_published_analytical_plan(
    plan: AnalyticalPlan,
    *,
    datasource: str,
    context: PublishedSemanticContext,
) -> BoundAnalyticalPlan:
    """Bind only against explicitly published records of one datasource.

    Publication flags and datasource identifiers must originate from the
    trusted catalog provider, never LLM output or user-supplied JSON.
    """
    if not isinstance(datasource, str) or not datasource.strip():
        raise ValueError("Requested datasource is required")
    if context.datasource.casefold() != datasource.casefold():
        raise ValueError("Governed context does not match requested datasource")
    return bind_analytical_plan(
        plan,
        approved_metrics=list(context.metrics),
        approved_dimensions=list(context.dimensions),
        approved_time_dimensions=list(context.time_dimensions),
    )
