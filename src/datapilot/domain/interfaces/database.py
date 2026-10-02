"""Database provider abstraction interface.

Defines the contract for database connectors (PostgreSQL, MySQL, Snowflake, BigQuery, etc.).
Decouples query execution and schema introspection from any specific database driver.
"""

from typing import Any, Dict, Optional, Protocol, runtime_checkable
from datapilot.domain.models import QueryResult, SchemaMetadata


@runtime_checkable
class DatabaseProvider(Protocol):
    """Protocol for target database adapters.

    Responsible for connectivity verification, schema introspection, and safe
    query execution against the connected analytical or operational database.
    """

    @property
    def dialect(self) -> str:
        """Return the database dialect identifier (e.g. 'postgresql', 'snowflake', 'mysql')."""
        ...

    async def ping(self) -> bool:
        """Verify that the database connection is alive and healthy."""
        ...

    async def introspect_schema(self, schema_name: Optional[str] = None) -> SchemaMetadata:
        """Extract database catalog, tables, columns, data types, and foreign keys."""
        ...

    async def execute_query(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> QueryResult:
        """Execute a validated read-only SQL query and return structured results."""
        ...

    async def close(self) -> None:
        """Gracefully release database pools and open connections."""
        ...
