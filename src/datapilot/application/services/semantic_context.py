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

        datasets = await self._metadata.list_semantic_datasets(source_id)
        entities = await self._metadata.list_semantic_entities(source_id)
        relationships = await self._metadata.list_semantic_relationships(source_id)
        metrics = await self._metadata.list_semantic_metrics(source_id)
        rules = await self._metadata.list_business_rules(source_id)

        entity_ids: set[int] = set()
        metric_ids: set[int] = set()
        dataset_keys: set[tuple[str, str]] = set()
        entity_seed_ids: set[int] = set()

        # First establish the dataset boundary independently of result ordering.
        for item in retrieved:
            meta = item.get("metadata") or {}
            if item.get("kind") == "dataset" and meta.get("schema_name") and meta.get("table_name"):
                dataset_keys.add((meta["schema_name"], meta["table_name"]))

        for item in retrieved:
            meta = item.get("metadata") or {}
            kind = item.get("kind")
            if kind == "entity" and meta.get("id") is not None:
                entity_seed_ids.add(int(meta["id"]))
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

        # Dataset-first boundary: when dataset semantics matched, they define the
        # semantic neighborhood. Vector-matched entities outside those datasets are
        # intentionally ignored. If no dataset matched, entity seeds remain the
        # backwards-compatible fallback for partially configured sources.
        if dataset_keys:
            for entity in entities:
                if (entity.get("schema_name"), entity.get("table_name")) in dataset_keys:
                    entity_ids.add(entity["id"])
        else:
            entity_ids.update(entity_seed_ids)

        # Intent seeds are subordinate to the structural boundary. A metric may
        # enrich a selected dataset/entity, but it must not pull an unrelated
        # physical dataset into the query neighborhood.
        bounded_metric_ids = {
            metric["id"] for metric in metrics
            if metric["id"] in metric_ids and metric["entity_id"] in entity_ids
        }

        # Graph expansion: include direct governed relationships touching selected
        # entities. If both endpoints are selected, the join is always relevant.
        selected_relationships = [
            r for r in relationships
            if r["from_entity_id"] in entity_ids and r["to_entity_id"] in entity_ids
        ]

        selected_entities = [e for e in entities if e["id"] in entity_ids]
        # When Stage 2 found metric intent, keep only those relevant metrics.
        # If no metric matched, retain entity metrics as a compatibility fallback
        # so non-metric questions and partially configured catalogs still work.
        selected_metrics = [
            m for m in metrics
            if (
                m["id"] in bounded_metric_ids
                if bounded_metric_ids
                else m["entity_id"] in entity_ids
            )
        ]
        selected_metric_ids = {m["id"] for m in selected_metrics}
        rule_seed_ids = {
            int((item.get("metadata") or {}).get("id"))
            for item in retrieved
            if item.get("kind") == "business_rule"
            and (item.get("metadata") or {}).get("id") is not None
        }
        applicable_rules = [
            r for r in rules
            if r.get("enabled", True)
            and (
                (r.get("entity_id") is not None and r["entity_id"] in entity_ids)
                or (r.get("metric_id") is not None and r["metric_id"] in selected_metric_ids)
            )
        ]
        # Prefer semantically retrieved rules, while keeping rules directly bound
        # to a selected metric because those define the metric's governed meaning.
        selected_rules = [
            r for r in applicable_rules
            if r["id"] in rule_seed_ids
            or (r.get("metric_id") is not None and r["metric_id"] in selected_metric_ids)
        ]

        selected_datasets = [
            d for d in datasets
            if (d.get("schema_name"), d.get("table_name")) in dataset_keys
        ]

        return {
            "datasets": selected_datasets,
            "entities": selected_entities,
            "relationships": selected_relationships,
            "metrics": selected_metrics,
            "business_rules": selected_rules,
        }
