"""Bind analytical plans using persisted metric, time and attribute grants.

Unlike the legacy entity-as-dimension loader, this entry point obtains
dimensions solely from explicit per-attribute publications.
"""
from __future__ import annotations

from typing import Any

from datapilot.application.services.analytical_dimension_loader import (
    load_published_analytical_dimensions,
)
from datapilot.application.services.analytical_metadata_loader import (
    load_persisted_analytical_context,
)
from datapilot.application.services.analytical_plan import AnalyticalPlan
from datapilot.application.services.analytical_plan_binding import (
    BoundAnalyticalPlan, bind_analytical_plan,
)


async def bind_governed_analytical_plan(
    *,
    plan: AnalyticalPlan,
    datasource: str,
    provider: Any,
    publication_store: Any,
    attribute_publication_store: Any,
) -> BoundAnalyticalPlan:
    """Resolve all plan references against a datasource-scoped approved snapshot.

    Legacy entity-level dimension grants are deliberately ignored. A
    dimension is available only through the attribute publication store.
    This does not compile or execute SQL.
    """
    if attribute_publication_store is None:
        raise ValueError("Attribute publication store is required")
    context = await load_persisted_analytical_context(
        provider=provider, datasource=datasource,
        publication_store=publication_store,
    )
    attributes = await load_published_analytical_dimensions(
        provider=provider, datasource=datasource,
        publication_store=attribute_publication_store,
    )
    dimensions = [
        {"name": f"{item.entity_name}.{item.name}"}
        for item in attributes
    ]
    # Unqualified names are exposed only when they resolve to one approved
    # attribute. Qualified names always remain available.
    counts: dict[str, int] = {}
    for item in attributes:
        key = item.name.casefold()
        counts[key] = counts.get(key, 0) + 1
    for item in attributes:
        if counts[item.name.casefold()] == 1:
            dimensions.append({"name": item.name})
    return bind_analytical_plan(
        plan,
        approved_metrics=list(context.metrics),
        approved_dimensions=dimensions,
        approved_time_dimensions=list(context.time_dimensions),
    )
