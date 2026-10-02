"""Application service for deterministic database schema discovery."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional, Pattern, Sequence

from datapilot.core.exceptions import MetadataError
from datapilot.domain.interfaces.database import DatabaseProvider
from datapilot.domain.interfaces.metadata import MetadataProvider
from datapilot.domain.models import SchemaMetadata


@dataclass(frozen=True)
class SchemaDiscoveryOptions:
    """Rules controlling which discovered database objects enter the catalog."""

    schema_name: Optional[str] = None
    excluded_tables: frozenset[str] = field(default_factory=frozenset)
    excluded_table_patterns: Sequence[Pattern[str]] = field(default_factory=tuple)


class SchemaDiscoveryService:
    """Discover, normalize, version, and optionally persist database metadata.

    The service deliberately contains no LLM calls. Schema discovery must remain
    deterministic so downstream semantic and SQL-generation components can rely
    on a stable catalog representation.
    """

    def __init__(
        self,
        database_provider: DatabaseProvider,
        metadata_provider: Optional[MetadataProvider] = None,
    ) -> None:
        self._database_provider = database_provider
        self._metadata_provider = metadata_provider

    async def discover(
        self,
        options: Optional[SchemaDiscoveryOptions] = None,
        *,
        persist: bool = False,
    ) -> SchemaMetadata:
        """Discover and normalize a schema from the configured database provider."""
        options = options or SchemaDiscoveryOptions()
        discovered = await self._database_provider.introspect_schema(options.schema_name)
        normalized = self._normalize(discovered, options)
        normalized.version = self._calculate_version(normalized)

        if persist:
            if self._metadata_provider is None:
                raise MetadataError("persist=True requires a MetadataProvider")
            await self._metadata_provider.save_schema(normalized)

        return normalized

    async def refresh(
        self,
        options: Optional[SchemaDiscoveryOptions] = None,
    ) -> SchemaMetadata:
        """Rediscover the schema and persist the resulting catalog snapshot."""
        return await self.discover(options, persist=True)

    @staticmethod
    def _normalize(schema: SchemaMetadata, options: SchemaDiscoveryOptions) -> SchemaMetadata:
        """Normalize ordering without mutating the provider's original objects."""
        excluded = {name.casefold() for name in options.excluded_tables}
        tables = []

        for table in schema.tables:
            if table.name.casefold() in excluded:
                continue
            if any(pattern.search(table.name) for pattern in options.excluded_table_patterns):
                continue

            table_copy = table.model_copy(deep=True)
            table_copy.columns.sort(key=lambda column: column.name.casefold())
            table_copy.primary_keys = sorted(table_copy.primary_keys, key=str.casefold)
            table_copy.foreign_keys.sort(
                key=lambda fk: (
                    fk.constrained_column.casefold(),
                    fk.referenced_table.casefold(),
                    fk.referenced_column.casefold(),
                )
            )
            tables.append(table_copy)

        tables.sort(key=lambda table: ((table.schema_name or "").casefold(), table.name.casefold()))

        return SchemaMetadata(
            tables=tables,
            dialect=schema.dialect,
            version=None,
        )

    @staticmethod
    def _calculate_version(schema: SchemaMetadata) -> str:
        """Return a stable short hash representing the catalog structure."""
        payload = schema.model_dump(mode="json", exclude={"version"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
