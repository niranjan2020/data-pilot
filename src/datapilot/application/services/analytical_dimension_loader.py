"""Load explicitly published analytical attributes from datasource metadata.

A published entity is not sufficient authorization for its attributes.
Each attribute must have a separate persistent publication grant.
"""
from __future__ import annotations

from typing import Any, Protocol

from datapilot.application.services.analytical_dimensions import (
    AnalyticalDimension,
    extract_analytical_dimensions,
)


class AttributePublicationChecker(Protocol):
    async def is_published(
        self, data_source_id: int, entity_id: int, attribute_name: str
    ) -> bool: ...


async def load_published_analytical_dimensions(
    *,
    provider: Any,
    datasource: str,
    publication_store: AttributePublicationChecker,
) -> tuple[AnalyticalDimension, ...]:
    """Return only explicitly approved attributes, never implicit entity grants.

    The provider must be trusted PostgreSQL semantic metadata, and the store
    must consult persisted attribute-level publication records.
    """
    if not isinstance(datasource, str) or not datasource.strip():
        raise ValueError("Datasource is required")
    if publication_store is None or not callable(
        getattr(publication_store, "is_published", None)
    ):
        raise ValueError("Attribute publication store is required")
    source_id = await provider.get_data_source_id(datasource)
    if type(source_id) is not int or source_id <= 0:
        raise ValueError("Unknown datasource")
    entities = await provider.list_semantic_entities(source_id)
    dimensions = extract_analytical_dimensions(entities)
    approved: list[AnalyticalDimension] = []
    for dimension in dimensions:
        if await publication_store.is_published(
            source_id, dimension.entity_id, dimension.name
        ) is True:
            approved.append(dimension)
    return tuple(approved)
