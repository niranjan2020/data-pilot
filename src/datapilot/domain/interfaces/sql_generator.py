"""SQL generator abstraction interface.

Defines the contract for synthesizing dialect-specific SQL queries from natural language
intents, semantic context, and relational schema information.
"""

from typing import Any, Dict, Optional, Protocol, runtime_checkable
from datapilot.domain.models import SchemaMetadata


@runtime_checkable
class SQLGenerator(Protocol):
    """Protocol for generating dialect-specific SQL queries.

    Implementations translate user question intents into executable SQL,
    incorporating business rules, templates, and schema metadata.
    """

    async def generate(
        self,
        question: str,
        schema: SchemaMetadata,
        context: Optional[Dict[str, Any]] = None,
        dialect: Optional[str] = None,
    ) -> str:
        """Generate an SQL query string based on question, schema, and context."""
        ...
