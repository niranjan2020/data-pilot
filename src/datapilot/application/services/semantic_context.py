"""Assemble concise governed semantic context for SQL generation."""

from __future__ import annotations

from typing import Any
import re

from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider


class SemanticContextAssembler:
    """Expand vector-search seeds through the authoritative semantic graph."""

    def __init__(self, metadata: PostgreSQLMetadataProvider) -> None:
        self._metadata = metadata

    async def carry_forward(
        self,
        source_name: str,
        current: dict[str, Any],
        conversation_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge prior governed lineage into a follow-up using authoritative metadata.

        Follow-ups may be elliptical, so retrieval for the new text can narrow
        away a metric or join needed from the parent turn. Rehydrate only persisted
        semantic names from PostgreSQL; prior SQL is never accepted or reused.
        """
        source_id = await self._metadata.get_data_source_id(source_name)
        if source_id is None or not conversation_context.get("previous_question"):
            return current

        entities = await self._metadata.list_semantic_entities(source_id)
        relationships = await self._metadata.list_semantic_relationships(source_id)
        metrics = await self._metadata.list_semantic_metrics(source_id)
        rules = await self._metadata.list_business_rules(source_id)
        datasets = await self._metadata.list_semantic_datasets(source_id)
        list_time_dimensions = getattr(self._metadata, "list_time_dimensions", None)
        time_dimensions = await list_time_dimensions(source_id) if list_time_dimensions else []

        prior_entity_names = set(conversation_context.get("governed_entities") or [])
        prior_metric_names = set(conversation_context.get("governed_metrics") or [])
        prior_rule_names = set(conversation_context.get("governed_business_rules") or [])
        prior_time_names = set(conversation_context.get("governed_time_dimensions") or [])

        entity_ids = {item["id"] for item in current.get("entities", [])}
        entity_ids.update(e["id"] for e in entities if e.get("name") in prior_entity_names)

        metric_ids = {item["id"] for item in current.get("metrics", [])}
        metric_ids.update(m["id"] for m in metrics if m.get("name") in prior_metric_names)
        # A carried metric always carries its authoritative owning entity so its
        # expression cannot reference a table omitted from physical schema binding.
        entity_ids.update(m["entity_id"] for m in metrics if m["id"] in metric_ids)

        selected_entities = [e for e in entities if e["id"] in entity_ids]
        selected_metrics = [m for m in metrics if m["id"] in metric_ids]
        selected_relationships = [
            r for r in relationships
            if r["from_entity_id"] in entity_ids and r["to_entity_id"] in entity_ids
        ]
        current_rule_ids = {item["id"] for item in current.get("business_rules", [])}
        selected_rules = [
            r for r in rules
            if r.get("enabled", True)
            and (r["id"] in current_rule_ids or r.get("name") in prior_rule_names)
            and (
                (r.get("entity_id") is not None and r["entity_id"] in entity_ids)
                or (r.get("metric_id") is not None and r["metric_id"] in metric_ids)
            )
        ]

        dataset_keys = {
            (e.get("schema_name"), e.get("table_name"))
            for e in selected_entities
            if e.get("schema_name") and e.get("table_name")
        }
        selected_datasets = [
            d for d in datasets
            if (d.get("schema_name"), d.get("table_name")) in dataset_keys
        ]
        existing_dataset_keys = {
            (d.get("schema_name"), d.get("table_name")) for d in selected_datasets
        }
        selected_datasets.extend(
            {
                "schema_name": schema_name,
                "table_name": table_name,
                "name": f"{schema_name}.{table_name}",
                "description": None,
            }
            for schema_name, table_name in sorted(dataset_keys - existing_dataset_keys)
        )

        current_time_ids = {item["id"] for item in current.get("time_dimensions", [])}
        selected_time_dimensions = [
            d for d in time_dimensions
            if d["entity_id"] in entity_ids
            and (d["id"] in current_time_ids or d.get("name") in prior_time_names)
        ]

        return {
            "datasets": selected_datasets,
            "entities": selected_entities,
            "relationships": selected_relationships,
            "metrics": selected_metrics,
            "business_rules": selected_rules,
            "time_dimensions": selected_time_dimensions,
        }

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
        list_time_dimensions = getattr(self._metadata, "list_time_dimensions", None)
        time_dimensions = await list_time_dimensions(source_id) if list_time_dimensions else []

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
        # Keep the most specific explicit entity phrase(s). A question such
        # as "show order lines" may also contain a shorter synonym such as
        # "order"; the longer governed phrase must win instead of selecting both
        # entities and widening the semantic boundary.
        explicit_entity_matches: list[tuple[int, int]] = []
        explicit_entity_phrases: dict[int, set[str]] = {}
        for entity in entities:
            best_specificity = 0
            terms = [entity.get("name") or "", *(entity.get("synonyms") or [])]
            for term in terms:
                normalized_term = re.sub(r"[^a-z0-9]+", " ", term.lower()).strip()
                term_variants = {normalized_term}
                if normalized_term:
                    words = normalized_term.split()
                    last_word = words[-1]
                    alternate_last = (
                        last_word[:-1] if last_word.endswith("s") else last_word + "s"
                    )
                    term_variants.add(" ".join([*words[:-1], alternate_last]))
                for variant in term_variants:
                    if variant and f" {variant} " in normalized_question:
                        best_specificity = max(best_specificity, len(variant.split()))
                        explicit_entity_phrases.setdefault(entity["id"], set()).add(variant)
            if best_specificity:
                explicit_entity_matches.append((entity["id"], best_specificity))

        max_entity_specificity = max(
            (specificity for _, specificity in explicit_entity_matches),
            default=0,
        )
        explicit_entity_ids: set[int] = {
            entity_id
            for entity_id, specificity in explicit_entity_matches
            if specificity == max_entity_specificity
        }

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
        # When an entity phrase is explicit, do not reinterpret a shorter metric
        # synonym contained wholly inside that phrase (for example a metric
        # synonym "sales" inside the entity phrase "sales orders").
        selected_entity_phrases = {
            phrase
            for entity_id in explicit_entity_ids
            for phrase in explicit_entity_phrases.get(entity_id, set())
        }
        explicit_metric_ids: set[int] = set()
        for metric in metrics:
            terms = [metric.get("name") or "", *(metric.get("synonyms") or [])]
            for term in terms:
                normalized_term = re.sub(r"[^a-z0-9]+", " ", term.lower()).strip()
                if normalized_term and f" {normalized_term} " in normalized_question:
                    metric_words = normalized_term.split()
                    shadowed_by_entity = any(
                        len(entity_phrase.split()) > len(metric_words)
                        and f" {normalized_term} " in f" {entity_phrase} "
                        for entity_phrase in selected_entity_phrases
                    )
                    if not shadowed_by_entity:
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

        # Temporal intent may require a governed date role that lives on a
        # directly related entity rather than on the metric owner. For example,
        # Revenue may live on Sales Order Line while Order Date lives on Sales
        # Order. Expand by one authoritative relationship hop only; never let
        # vector retrieval invent the temporal join.
        temporal_intent = bool(re.search(
            r"\b(today|yesterday|ytd|year to date|daily|weekly|monthly|quarterly|yearly|"
            r"trend|this month|last month|previous month|this quarter|last quarter|"
            r"previous quarter|this year|last year|previous year|last [0-9]+ days?|"
            r"past [0-9]+ days?|last [0-9]+ months?|past [0-9]+ months?|by day|by week|"
            r"by month|by quarter|by year)\b",
            normalized_question,
        ))
        selected_time_dimension_ids: set[int] = set()
        if temporal_intent and time_dimensions:
            explicit_time_dimensions: list[dict[str, Any]] = []
            for dimension in time_dimensions:
                terms = [
                    dimension.get("name") or "",
                    dimension.get("role") or "",
                    *(dimension.get("synonyms") or []),
                ]
                if any(
                    term
                    and f" {re.sub(r'[^a-z0-9]+', ' ', term.lower()).strip()} " in normalized_question
                    for term in terms
                ):
                    explicit_time_dimensions.append(dimension)

            candidates = explicit_time_dimensions or [
                dimension for dimension in time_dimensions if dimension.get("is_default")
            ]
            connected_candidates: list[dict[str, Any]] = []
            for dimension in candidates:
                target_id = dimension["entity_id"]
                if target_id in entity_ids:
                    connected_candidates.append(dimension)
                    continue
                if any(
                    (relationship["from_entity_id"] in entity_ids and relationship["to_entity_id"] == target_id)
                    or (relationship["to_entity_id"] in entity_ids and relationship["from_entity_id"] == target_id)
                    for relationship in relationships
                ):
                    connected_candidates.append(dimension)

            # Preserve multiple equally governed candidates so the deterministic
            # time resolver can return ambiguity rather than silently choosing.
            for dimension in connected_candidates:
                selected_time_dimension_ids.add(dimension["id"])
                entity_ids.add(dimension["entity_id"])
                entity = next((e for e in entities if e["id"] == dimension["entity_id"]), None)
                if entity:
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
        if explicit_metric_ids:
            selected_metrics = [m for m in metrics if m["id"] in bounded_metric_ids]
        elif explicit_entity_ids:
            selected_metrics = []
        elif bounded_metric_ids:
            selected_metrics = [m for m in metrics if m["id"] in bounded_metric_ids]
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
            "time_dimensions": [
                dimension for dimension in time_dimensions
                if dimension["entity_id"] in entity_ids
                and (not temporal_intent or not selected_time_dimension_ids or dimension["id"] in selected_time_dimension_ids)
            ],
        }
