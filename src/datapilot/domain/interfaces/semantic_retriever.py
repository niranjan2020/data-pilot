"""Runtime semantic retrieval contract."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SemanticRetriever(Protocol):
    """Retrieve governed semantic context relevant to one question."""

    async def search(
        self, source_name: str, question: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        ...
