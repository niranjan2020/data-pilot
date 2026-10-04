"""Assemble concise governed semantic context for SQL generation."""

from __future__ import annotations

from typing import Any
import re

from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider


class SemanticContextAssembler:
    """Expand vector-search seeds through the authoritative semantic graph."""

    def __init__(self, metadata: PostgreSQLMetadataProvider) -> None:
        self._metadata = metadata

    async def assemble(
        self, source_name: str, retrieved: list[dict[str, Any]], question: str = ""
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
            elif kind == "business_rule":
                # Rules are intent evidence only. They must never widen the
                # Stage-1 structural dataset/entity boundary.
                if meta.get("metric_id") is not None:
                    metric_ids.add(int(meta["metric_id"]))

        # Exact business vocabulary in the question is stronger evidence than
        # approximate vector neighbours. Use explicitly mentioned entity names or
        # synonyms as structural anchors so a broad top-k search cannot widen a
        # simple question such as "show all products".
        normalized_question = " " + re.sub(r"[^a-z0-9]+", " ", question.lower()).strip() + " "
        explicit_entity_ids: set[int] = set()
        for entity in entities:
            terms = [entity.get("name") or "", *(entity.get("synonyms") or [])]
            for term in terms:
                normalized_term = re.sub(r"[^a-z0-9]+", " ", term.lower()).strip()
                # Business users naturally alternate singular/plural nouns
                # ("product" / "products"). Treat a simple trailing-s plural as
                # the same explicit semantic term without introducing a domain
                # dictionary or fuzzy vector decision.
                term_variants = {normalized_term}
                if normalized_term:
                    words = normalized_term.split()
                    last_word = words[-1]
                    # Apply the same simple singular/plural normalization to the
                    # head noun of multi-word business terms too: "sales order"
                    # should explicitly anchor "sales orders", and "order line"
                    # should anchor "order lines".
                    alternate_last = (
                        last_word[:-1] if last_word.endswith("s") else last_word + "s"
                    )
                    term_variants.add(" ".join([*words[:-1], alternate_last]))
                if any(variant and f" {variant} " in normalized_question for variant in term_variants):
                    explicit_entity_ids.add(entity["id"])
                    break

        if explicit_entity_ids:
            entity_ids = set(explicit_entity_ids)
            dataset_keys = {
                (entity.get("schema_name"), entity.get("table_name"))
                for entity in entities
                if entity["id"] in explicit_entity_ids
                and entity.get("schema_name") and entity.get("table_name")
            }
        elif dataset_keys:
            for entity in entities:
                if (entity.get("schema_name"), entity.get("table_name")) in dataset_keys:
                    entity_ids.add(entity["id"])
        else:
            entity_ids.update(entity_seed_ids)

        # Prefer explicit configured metric names/synonyms in the question.
        # This is deterministic semantic resolution, not business-specific logic,
        # and supports multiple explicitly requested metrics.
        explicit_metric_ids: set[int] = set()
        for metric in metrics:
            terms = [metric.get("name") or "", *(metric.get("synonyms") or [])]
            for term in terms:
                normalized_term = re.sub(r"[^a-z0-9]+", " ", term.lower()).strip()
                if normalized_term and f" {normalized_term} " in normalized_question:
                    explicit_metric_ids.add(metric["id"])
                    break
        if explicit_metric_ids:
            metric_ids = explicit_metric_ids
            # An explicitly named governed metric is also structural evidence:
            # include its owning entity. This allows questions such as "order
            # count by customer" to connect the Customer anchor to the Sales Order
            # metric owner without trusting unrelated vector neighbours.
            metric_owner_ids = {
                metric["entity_id"] for metric in metrics
                if metric["id"] in explicit_metric_ids
            }
            entity_ids.update(metric_owner_ids)
            for entity in entities:
                if entity["id"] in metric_owner_ids:
                    dataset_keys.add((entity.get("schema_name"), entity.get("table_name")))

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
        # An explicit entity-only question should not inherit every metric owned by
        # nearby vector candidates. Metric fallback is only useful when there is no
        # explicit entity anchor and no explicit metric intent.
        if bounded_metric_ids:
            selected_metrics = [m for m in metrics if m["id"] in bounded_metric_ids]
        elif explicit_entity_ids:
            selected_metrics = []
        else:
            selected_metrics = [m for m in metrics if m["entity_id"] in entity_ids]
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

        # Keep the dataset boundary synchronized with the final governed
        # entity boundary. Explicit metric resolution can add its owning entity
        # after the initial dataset seeds were chosen, and every selected entity
        # must expose its authoritative physical dataset to downstream tracing
        # and schema pruning.
        final_dataset_keys = {
            (entity.get("schema_name"), entity.get("table_name"))
            for entity in selected_entities
            if entity.get("schema_name") and entity.get("table_name")
        }
        selected_datasets = [
            d for d in datasets
            if (d.get("schema_name"), d.get("table_name")) in final_dataset_keys
        ]
        # Dataset metadata is optional governance enrichment; an entity's
        # authoritative schema/table mapping must still define the physical
        # boundary even when no separate dataset-info record was configured.
        # Synthesize only the minimal boundary record needed downstream/trace.
        selected_dataset_keys = {
            (d.get("schema_name"), d.get("table_name")) for d in selected_datasets
        }
        selected_datasets.extend(
            {
                "schema_name": schema_name,
                "table_name": table_name,
                "name": f"{schema_name}.{table_name}",
                "description": None,
            }
            for schema_name, table_name in sorted(final_dataset_keys - selected_dataset_keys)
        )

        return {
            "datasets": selected_datasets,
            "entities": selected_entities,
            "relationships": selected_relationships,
            "metrics": selected_metrics,
            "business_rules": selected_rules,
        }
