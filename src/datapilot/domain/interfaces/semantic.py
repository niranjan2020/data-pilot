"""Semantic catalog persistence contract."""

from typing import Optional, Protocol, runtime_checkable

from datapilot.domain.semantic import SemanticCatalog


@runtime_checkable
class SemanticCatalogProvider(Protocol):
    """Persist and retrieve business semantic definitions."""

    async def get_catalog(self) -> SemanticCatalog:
        """Return the current semantic catalog."""
        ...

    async def save_catalog(self, catalog: SemanticCatalog) -> None:
        """Persist the supplied semantic catalog."""
        ...
