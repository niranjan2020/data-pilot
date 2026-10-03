"""Assemble concise governed semantic context for SQL generation."""

from __future__ import annotations

from typing import Any

from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider


class SemanticContextAssembler:
    """Expand vector-search seeds through the authoritative semantic graph."""

    def __init__(self, metadata: PostgreSQLMetadataProvider) -> None:
        self._metadata = metadata

    async def assemble(
        self, source_name: str, retrieved: list[dict[str, Any]]
    ) -> dict[str, Any]:
        source_id = await self._metadata.get_data_source_id(source_name)
        if source_id is None:
            return {"entities": [], "relationships": [], "metrics": [], "business_rules": []}

        entities = await self._metadata.list_semantic_entities(source_id)
        relationships = await self._metadata.list_semantic_relationships(source_id)
        metrics = await self._metadata.list_semantic_metrics(source_id)
        rules = await self._metadata.list_business_rules(source_id)

        entity_ids: set[int] = set()
        metric_ids: set[int] = set()

        for item in retrieved:
            meta = item.get("metadata") or {}
            kind = item.get("kind")
            if kind == "entity" and meta.get("id") is not None:
                entity_ids.add(int(meta["id"]))
            elif kind == "relationship":
                for key in ("from_entity_id", "to_entity_id"):
                    if meta.get(key) is not None:
                        entity_ids.add(int(meta[key]))
            elif kind == "metric":
                if meta.get("id") is not None:
                    metric_ids.add(int(meta["id"]))
                if meta.get("entity_id") is not None:
                    entity_ids.add(int(meta["entity_id"]))
            elif kind == "business_rule":
                if meta.get("entity_id") is not None:
                    entity_ids.add(int(meta["entity_id"]))
                if meta.get("metric_id") is not None:
                    metric_ids.add(int(meta["metric_id"]))

        # Metrics imply their owning entity.
        for metric in metrics:
            if metric["id"] in metric_ids:
                entity_ids.add(metric["entity_id"])

        # Graph expansion: include direct governed relationships touching selected
        # entities. If both endpoints are selected, the join is always relevant.
        selected_relationships = [
            r for r in relationships
            if r["from_entity_id"] in entity_ids and r["to_entity_id"] in entity_ids
        ]

        selected_entities = [e for e in entities if e["id"] in entity_ids]
        selected_metrics = [
            m for m in metrics if m["id"] in metric_ids or m["entity_id"] in entity_ids
        ]
        selected_metric_ids = {m["id"] for m in selected_metrics}
        selected_rules = [
            r for r in rules
            if r.get("enabled", True)
            and (
                (r.get("entity_id") is not None and r["entity_id"] in entity_ids)
                or (r.get("metric_id") is not None and r["metric_id"] in selected_metric_ids)
            )
        ]

        return {
            "entities": selected_entities,
            "relationships": selected_relationships,
            "metrics": selected_metrics,
            "business_rules": selected_rules,
        }
