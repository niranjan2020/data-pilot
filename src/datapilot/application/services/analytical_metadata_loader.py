"""Load datasource-scoped analytical metadata from the existing provider.

The existing semantic metric/entity/time tables do not expose an explicit
publication flag. Consequently, this loader requires a separate trusted
authorization function; it never promotes catalog existence into approval.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from datapilot.application.services.analytical_context_adapter import (
    build_published_analytical_context,
)
from datapilot.application.services.published_analytical_context import PublishedSemanticContext


class AnalyticalMetadataProvider(Protocol):
    async def get_data_source_id(self, name: str) -> int | None: ...
    async def list_semantic_entities(self, data_source_id: int) -> list[dict]: ...
    async def list_semantic_metrics(self, data_source_id: int) -> list[dict]: ...
    async def list_time_dimensions(self, data_source_id: int) -> list[dict]: ...


# Authorization is deliberately a separate provider-owned decision.
PublicationAuthorizer = Callable[[int, str, int], Awaitable[bool]]


async def load_published_analytical_context(
    *,
    provider: AnalyticalMetadataProvider,
    datasource: str,
    authorize: PublicationAuthorizer,
) -> PublishedSemanticContext:
    """Load catalog records, then verify each ID with a trusted authorizer.

    The authorizer must consult persistent publication governance. The
    PostgreSQL metadata provider currently has no such publication mechanism
    for metrics and time dimensions, so callers must not pass allow-all.
    """
    if not datasource or not datasource.strip():
        raise ValueError("Datasource is required")
    if not callable(authorize):
        raise ValueError("Trusted publication authorizer is required")
    source_id = await provider.get_data_source_id(datasource)
    if source_id is None:
        raise ValueError("Unknown datasource")

    entities = await provider.list_semantic_entities(source_id)
    metrics = await provider.list_semantic_metrics(source_id)
    time_dimensions = await provider.list_time_dimensions(source_id)

    async def verify(kind: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        approved: list[dict[str, Any]] = []
        for record in records:
            identifier = record.get("id")
            if type(identifier) is not int or identifier < 1:
                raise ValueError(f"Invalid {kind} metadata identifier")
            if not await authorize(source_id, kind, identifier):
                # Unpublished catalog entries are excluded, not made available
                # to the planner simply because they exist in metadata.
                continue
            approved.append({"id": identifier, "name": record["name"], "datasource": datasource})
        return approved

    approved_metrics = await verify("metric", metrics)
    approved_entities = await verify("dimension", entities)
    approved_times = await verify("time_dimension", time_dimensions)
    # The adapter validates the immutable, datasource-scoped records. Approval
    # has already been verified against persistent governance above.
    return build_published_analytical_context(
        datasource=datasource,
        metrics=approved_metrics,
        dimensions=approved_entities,
        time_dimensions=approved_times,
        is_published=lambda kind, record: True,
    )


async def load_persisted_analytical_context(
    *,
    provider: AnalyticalMetadataProvider,
    datasource: str,
    publication_store: Any,
) -> PublishedSemanticContext:
    """Load semantic definitions using persisted, datasource-scoped grants.

    This is the production-oriented entry point. The store must expose the
    async is_published(data_source_id, kind, semantic_id) contract. Do not
    replace it with a permissive fallback if governance is unavailable.
    """
    if publication_store is None or not callable(
        getattr(publication_store, "is_published", None)
    ):
        raise ValueError("A persistent analytical publication store is required")
    return await load_published_analytical_context(
        provider=provider,
        datasource=datasource,
        authorize=publication_store.is_published,
    )
