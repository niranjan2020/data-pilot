"""Contract for resolving natural-language entities and values."""

from typing import Protocol, runtime_checkable

from datapilot.domain.models import SchemaMetadata
from datapilot.domain.semantic import QueryIntent, SemanticCatalog


@runtime_checkable
class EntityResolver(Protocol):
    """Resolve semantic entities and filters without prescribing an LLM or database."""

    def resolve(
        self,
        question: str,
        catalog: SemanticCatalog,
        schema: SchemaMetadata,
    ) -> QueryIntent:
        """Resolve the question into a structured semantic intent."""
        ...
