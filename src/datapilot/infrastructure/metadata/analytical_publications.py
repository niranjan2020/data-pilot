"""Persistence contract for explicitly approved analytical semantic definitions.

Publication is independent of semantic catalog existence. This table is
additive and defaults to no grants; legacy queries are not routed through it.
"""

ANALYTICAL_PUBLICATION_DDL = """
CREATE TABLE IF NOT EXISTS datapilot_catalog.analytical_semantic_publications (
    data_source_id BIGINT NOT NULL
        REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE,
    semantic_kind TEXT NOT NULL
        CHECK (semantic_kind IN ('metric', 'dimension', 'time_dimension')),
    semantic_id BIGINT NOT NULL CHECK (semantic_id > 0),
    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (data_source_id, semantic_kind, semantic_id)
)
"""

# Semantic IDs are validated against the owning catalog table at publication
# time. This avoids cross-datasource grants and stale/missing definitions.
SEMANTIC_OWNER_TABLE = {
    "metric": "datapilot_catalog.semantic_metrics",
    "dimension": "datapilot_catalog.semantic_entities",
    "time_dimension": "datapilot_catalog.semantic_time_dimensions",
}


def publication_table_for(kind: str) -> str:
    try:
        return SEMANTIC_OWNER_TABLE[kind]
    except (KeyError, TypeError) as exc:
        raise ValueError("Unsupported analytical semantic kind") from exc


class AnalyticalPublicationStore:
    """Datasource-scoped publication operations using the metadata pool."""

    def __init__(self, metadata_provider):
        self._metadata = metadata_provider

    async def _connection_pool(self):
        await self._metadata.initialize()
        return await self._metadata._get_pool()

    async def publish(self, *, data_source_id: int, kind: str, semantic_id: int) -> None:
        table = publication_table_for(kind)
        _validate_ids(data_source_id, semantic_id)
        pool = await self._connection_pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(ANALYTICAL_PUBLICATION_DDL)
                    # Whitelisted table identifier; IDs remain query parameters.
                    await cursor.execute(
                        f"SELECT 1 FROM {table} WHERE id = %s AND data_source_id = %s",
                        (semantic_id, data_source_id),
                    )
                    if await cursor.fetchone() is None:
                        raise ValueError("Semantic definition does not belong to datasource")
                    await cursor.execute(
                        """
                        INSERT INTO datapilot_catalog.analytical_semantic_publications
                            (data_source_id, semantic_kind, semantic_id)
                        VALUES (%s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (data_source_id, kind, semantic_id),
                    )

    async def revoke(self, *, data_source_id: int, kind: str, semantic_id: int) -> None:
        publication_table_for(kind)
        _validate_ids(data_source_id, semantic_id)
        pool = await self._connection_pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(ANALYTICAL_PUBLICATION_DDL)
                    await cursor.execute(
                        """
                        DELETE FROM datapilot_catalog.analytical_semantic_publications
                        WHERE data_source_id = %s AND semantic_kind = %s AND semantic_id = %s
                        """,
                        (data_source_id, kind, semantic_id),
                    )

    async def is_published(self, data_source_id: int, kind: str, semantic_id: int) -> bool:
        table = publication_table_for(kind)
        _validate_ids(data_source_id, semantic_id)
        pool = await self._connection_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(ANALYTICAL_PUBLICATION_DDL)
                await cursor.execute(
                    f"""
                    SELECT 1
                    FROM datapilot_catalog.analytical_semantic_publications p
                    JOIN {table} s ON s.id = p.semantic_id
                    WHERE p.data_source_id = %s AND p.semantic_kind = %s
                      AND p.semantic_id = %s AND s.data_source_id = %s
                    """,
                    (data_source_id, kind, semantic_id, data_source_id),
                )
                return await cursor.fetchone() is not None


def _validate_ids(data_source_id: int, semantic_id: int) -> None:
    if type(data_source_id) is not int or data_source_id <= 0:
        raise ValueError("Invalid datasource identifier")
    if type(semantic_id) is not int or semantic_id <= 0:
        raise ValueError("Invalid semantic identifier")
