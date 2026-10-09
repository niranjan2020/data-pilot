"""Read-only golden readiness using persisted datasource publication grants.

This integration never executes SQL or modifies the live NL-to-SQL route.
Publication-store failures are propagated, never treated as permission grants.
"""
from __future__ import annotations

from typing import Any

from datapilot.application.services.analytical_dimension_loader import (
    load_published_analytical_dimensions,
)
from datapilot.application.services.analytical_metadata_loader import (
    load_persisted_analytical_context,
)
from datapilot.application.services.analytical_golden_questions import GoldenAnalyticalQuestion
from datapilot.application.services.analytical_golden_readiness import (
    GoldenCatalogReadiness, validate_golden_catalog_readiness,
)


async def evaluate_published_golden_readiness(
    *,
    cases: tuple[GoldenAnalyticalQuestion, ...],
    datasource: str,
    provider: Any,
    publication_store: Any,
    attribute_publication_store: Any,
) -> tuple[GoldenCatalogReadiness, ...]:
    """Load trusted grants once per datasource, then evaluate each expectation.

    Callers must supply trusted provider and persisted stores, not user or LLM
    authored catalog snapshots. A missing or broken store is an error.
    """
    if not isinstance(cases, tuple) or any(
        not isinstance(case, GoldenAnalyticalQuestion) for case in cases
    ):
        raise ValueError("Golden cases must be a tuple of typed questions")
    if not isinstance(datasource, str) or not datasource.strip():
        raise ValueError("Datasource is required")
    if provider is None:
        raise ValueError("Trusted metadata provider is required")
    if publication_store is None or not callable(
        getattr(publication_store, "is_published", None)
    ):
        raise ValueError("Persistent publication store is required")
    if attribute_publication_store is None or not callable(
        getattr(attribute_publication_store, "is_published", None)
    ):
        raise ValueError("Persistent attribute publication store is required")
    ids = [case.expectation.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate golden case id")
    if not cases:
        return ()
    context = await load_persisted_analytical_context(
        provider=provider, datasource=datasource, publication_store=publication_store,
    )
    attributes = await load_published_analytical_dimensions(
        provider=provider, datasource=datasource,
        publication_store=attribute_publication_store,
    )
    return tuple(
        validate_golden_catalog_readiness(
            case, context=context, published_attributes=attributes, datasource=datasource,
        )
        for case in cases
    )
