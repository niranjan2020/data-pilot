"""Port for binding generated SQL to the physical database catalog."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from datapilot.domain.models import SchemaMetadata


@runtime_checkable
class SQLIdentifierBinder(Protocol):
    """Bind generated identifiers using the active target database dialect."""

    def bind(self, sql: str, schema: SchemaMetadata, dialect: str) -> str:
        """Return SQL whose identifiers are bound to the discovered catalog."""
        ...
