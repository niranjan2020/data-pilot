"""Administrative workflow for governed analytical semantic publication.

This service does not authenticate users. Its caller MUST supply an
authorization decision from the application's trusted admin access layer.
No publication is granted implicitly when semantic definitions are saved.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class PublicationRepository(Protocol):
    async def publish(self, *, data_source_id: int, kind: str, semantic_id: int) -> None: ...
    async def revoke(self, *, data_source_id: int, kind: str, semantic_id: int) -> None: ...
    async def is_published(self, data_source_id: int, kind: str, semantic_id: int) -> bool: ...


@dataclass(frozen=True)
class PublicationDecision:
    data_source_id: int
    kind: str
    semantic_id: int
    published: bool


class AnalyticalPublicationAdmin:
    """Explicit admin decisions, independent of domain and datasource."""

    def __init__(self, repository: PublicationRepository):
        if repository is None:
            raise ValueError("Publication repository is required")
        self._repository = repository

    @staticmethod
    def _require_authorized(authorized: bool) -> None:
        if authorized is not True:
            raise PermissionError("Administrative publication permission required")

    async def set_publication(
        self, *, data_source_id: int, kind: str, semantic_id: int,
        published: bool, authorized: bool,
    ) -> PublicationDecision:
        self._require_authorized(authorized)
        if type(published) is not bool:
            raise ValueError("Publication decision must be a boolean")
        # The repository validates semantic ownership and the allowlisted kind.
        if published:
            await self._repository.publish(
                data_source_id=data_source_id, kind=kind, semantic_id=semantic_id,
            )
        else:
            await self._repository.revoke(
                data_source_id=data_source_id, kind=kind, semantic_id=semantic_id,
            )
        return PublicationDecision(
            data_source_id=data_source_id, kind=kind,
            semantic_id=semantic_id, published=published,
        )

    async def get_publication(
        self, *, data_source_id: int, kind: str, semantic_id: int,
        authorized: bool,
    ) -> PublicationDecision:
        self._require_authorized(authorized)
        published = await self._repository.is_published(data_source_id, kind, semantic_id)
        return PublicationDecision(
            data_source_id=data_source_id, kind=kind,
            semantic_id=semantic_id, published=published,
        )
