"""Rebuildable Qdrant index for Data Pilot semantic metadata."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models


class QdrantSemanticIndex:
    """Index and retrieve semantic documents without making Qdrant authoritative."""

    def __init__(self, url: str, collection: str, embedding_model: str) -> None:
        self.client = QdrantClient(url=url)
        self.collection = collection
        self.embedder = TextEmbedding(model_name=embedding_model)

    @staticmethod
    def _point_id(source_name: str, kind: str, key: str) -> int:
        raw = f"{source_name}:{kind}:{key}".encode()
        return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") >> 1

    @staticmethod
    def _entity_text(entity: dict) -> str:
        attrs = "; ".join(
            f"{a['name']} ({a['column_name']}): {a.get('description') or ''} "
            f"synonyms {' '.join(a.get('synonyms') or [])}"
            for a in entity.get("attributes", [])
        )
        return (
            f"Entity {entity['name']}. {entity.get('description') or ''}. "
            f"Synonyms {' '.join(entity.get('synonyms') or [])}. "
            f"Physical table {entity['schema_name']}.{entity['table_name']}. Attributes: {attrs}"
        )

    def build_documents(
        self, source_name: str, entities: list[dict], relationships: list[dict],
        metrics: list[dict], rules: list[dict],
    ) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = []
        for e in entities:
            docs.append({"kind": "entity", "key": str(e["id"]), "name": e["name"],
                         "text": self._entity_text(e), "metadata": e})
        for r in relationships:
            text = (f"Relationship {r['name']}. {r['from_entity_name']}.{r['from_column']} "
                    f"to {r['to_entity_name']}.{r['to_column']}. {r['cardinality']}. "
                    f"{r.get('description') or ''}")
            docs.append({"kind": "relationship", "key": str(r["id"]), "name": r["name"],
                         "text": text, "metadata": r})
        for m in metrics:
            text = (f"Metric {m['name']}. {m.get('description') or ''}. "
                    f"{m['aggregation']} of {m['entity_name']}.{m['attribute_name']}. "
                    f"Synonyms {' '.join(m.get('synonyms') or [])}. Format {m['format']}.")
            docs.append({"kind": "metric", "key": str(m["id"]), "name": m["name"],
                         "text": text, "metadata": m})
        for r in rules:
            if not r.get("enabled", True):
                continue
            target = r.get("entity_name") or r.get("metric_name") or ""
            text = (f"Business rule {r['name']}. Type {r['rule_type']}. Target {target}. "
                    f"{r['description']}. Keywords {' '.join(r.get('keywords') or [])}.")
            docs.append({"kind": "business_rule", "key": str(r["id"]), "name": r["name"],
                         "text": text, "metadata": r})
        for d in docs:
            d["source_name"] = source_name
        return docs

    def rebuild(self, source_name: str, documents: list[dict[str, Any]]) -> int:
        texts = [d["text"] for d in documents]
        vectors = list(self.embedder.embed(texts)) if texts else []
        if vectors:
            size = len(vectors[0])
            collections = {c.name for c in self.client.get_collections().collections}
            if self.collection not in collections:
                self.client.create_collection(
                    collection_name=self.collection,
                    vectors_config=models.VectorParams(size=size, distance=models.Distance.COSINE),
                )
            self.client.delete(
                collection_name=self.collection,
                points_selector=models.FilterSelector(
                    filter=models.Filter(must=[
                        models.FieldCondition(key="source_name", match=models.MatchValue(value=source_name))
                    ])
                ),
            )
            points = [
                models.PointStruct(
                    id=self._point_id(source_name, d["kind"], d["key"]),
                    vector=v.tolist(),
                    payload=d,
                )
                for d, v in zip(documents, vectors)
            ]
            self.client.upsert(collection_name=self.collection, points=points, wait=True)
        return len(documents)

    async def search_async(self, source_name: str, question: str, limit: int = 8) -> list[dict[str, Any]]:
        """Async runtime port; embedding/Qdrant client work is moved off the event loop."""
        return await asyncio.to_thread(self.search, source_name, question, limit)

    def search(self, source_name: str, question: str, limit: int = 8) -> list[dict[str, Any]]:
        vector = list(self.embedder.embed([question]))[0].tolist()
        result = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            query_filter=models.Filter(must=[
                models.FieldCondition(key="source_name", match=models.MatchValue(value=source_name))
            ]),
            limit=limit,
            with_payload=True,
        )
        return [
            {"score": round(float(p.score), 4), **(p.payload or {})}
            for p in result.points
        ]
