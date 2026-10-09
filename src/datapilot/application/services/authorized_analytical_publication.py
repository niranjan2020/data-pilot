"""Trusted administrative authorization boundary for publication operations.

HTTP request fields must never be passed as the 'authorized' argument to
AnalyticalPublicationAdmin. This adapter resolves access using a server-owned
authorizer and passes only its decision to the existing service.
"""
from __future__ import annotations

from typing import Protocol

from datapilot.application.services.analytical_publication_admin import (
    AnalyticalPublicationAdmin, PublicationDecision,
)


class AdminAccessAuthorizer(Protocol):
    async def can_manage_analytical_publications(
        self, *, principal_id: str, data_source_id: int
    ) -> bool: ...


class AuthorizedAnalyticalPublicationWorkflow:
    def __init__(
        self,
        *,
        publication_admin: AnalyticalPublicationAdmin,
        authorizer: AdminAccessAuthorizer,
    ):
        if publication_admin is None or authorizer is None or not callable(
            getattr(authorizer, "can_manage_analytical_publications", None)
        ):
            raise ValueError("Trusted publication administrator and authorizer are required")
        self._admin = publication_admin
        self._authorizer = authorizer

    async def _authorize(self, *, principal_id: str, data_source_id: int) -> None:
        if not isinstance(principal_id, str) or not principal_id.strip():
            raise PermissionError("Authenticated administrative principal required")
        allowed = await self._authorizer.can_manage_analytical_publications(
            principal_id=principal_id, data_source_id=data_source_id,
        )
        if allowed is not True:
            raise PermissionError("Administrative publication permission required")

    async def set_publication(
        self, *, principal_id: str, data_source_id: int, kind: str,
        semantic_id: int, published: bool,
    ) -> PublicationDecision:
        await self._authorize(principal_id=principal_id, data_source_id=data_source_id)
        return await self._admin.set_publication(
            data_source_id=data_source_id, kind=kind,
            semantic_id=semantic_id, published=published, authorized=True,
        )

    async def get_publication(
        self, *, principal_id: str, data_source_id: int,
        kind: str, semantic_id: int,
    ) -> PublicationDecision:
        await self._authorize(principal_id=principal_id, data_source_id=data_source_id)
        return await self._admin.get_publication(
            data_source_id=data_source_id, kind=kind,
            semantic_id=semantic_id, authorized=True,
        )
