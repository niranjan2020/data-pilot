"""Deterministic prompt-context budgeting for SQL generation."""

from __future__ import annotations

import json
from typing import Any


class ContextBudgeter:
    """Keep authoritative context first and trim optional retrieval evidence."""

    def __init__(self, max_chars: int = 24000) -> None:
        self.max_chars = max_chars

    @staticmethod
    def _size(value: Any) -> int:
        return len(json.dumps(value, default=str, separators=(",", ":")))

    def apply(self, context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        result = dict(context)
        original_size = self._size(result)
        dropped: list[str] = []

        # Raw vector hits are debugging evidence, not authoritative generation
        # context. Drop them first when the prompt budget is exceeded.
        if original_size > self.max_chars and result.get("retrieved_semantic_context"):
            result["retrieved_semantic_context"] = []
            dropped.append("retrieved_semantic_context")

        # The complete catalog is a compatibility aid. Governed semantic context
        # plus the pruned physical schema are authoritative for this query.
        if self._size(result) > self.max_chars and result.get("semantic_catalog"):
            result["semantic_catalog"] = {}
            dropped.append("semantic_catalog")

        final_size = self._size(result)
        return result, {
            "max_chars": self.max_chars,
            "original_chars": original_size,
            "final_chars": final_size,
            "dropped": dropped,
            "within_budget": final_size <= self.max_chars,
        }
