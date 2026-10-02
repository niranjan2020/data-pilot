"""Metadata provider and repository abstraction interface.

Defines the contract for storing, enriching, and retrieving business metadata,
table annotations, semantic metrics, and discovered schemas.
"""

from typing import List, Optional, Protocol, runtime_checkable
from datapilot.domain.models import SchemaMetadata, TableMetadata


@runtime_checkable
class MetadataProvider(Protocol):
    """Protocol for persisting and discovering enriched catalog metadata.

    Allows Data Pilot to maintain business definitions, column meanings, and
    metric mappings without altering the underlying database.
    """

    async def get_schema(self, schema_name: Optional[str] = None) -> Optional[SchemaMetadata]:
        """Retrieve cached or stored schema metadata."""
        ...

    async def save_schema(self, schema: SchemaMetadata) -> None:
        """Persist or update schema metadata in the metadata store."""
        ...

    async def get_table(self, table_name: str, schema_name: Optional[str] = None) -> Optional[TableMetadata]:
        """Retrieve metadata for a specific table."""
        ...

    async def list_tables(self, schema_name: Optional[str] = None) -> List[str]:
        """List all indexed table names in the catalog."""
        ...
