"""Explicit per-attribute analytical dimension publication.

Entity approval is not attribute approval. The identity is the existing
semantic entity ID plus its governed attribute name, scoped to datasource.
This is additive; no legacy grants are migrated implicitly.
"""

ATTRIBUTE_DIMENSION_PUBLICATION_DDL = """
CREATE TABLE IF NOT EXISTS datapilot_catalog.analytical_attribute_publications (
    data_source_id BIGINT NOT NULL
        REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE,
    entity_id BIGINT NOT NULL
        REFERENCES datapilot_catalog.semantic_entities(id) ON DELETE CASCADE,
    attribute_name TEXT NOT NULL CHECK (length(trim(attribute_name)) > 0),
    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (data_source_id, entity_id, attribute_name)
)
"""


def _validate(data_source_id: int, entity_id: int, attribute_name: str) -> None:
    if type(data_source_id) is not int or data_source_id <= 0:
        raise ValueError("Invalid datasource identifier")
    if type(entity_id) is not int or entity_id <= 0:
        raise ValueError("Invalid entity identifier")
    if not isinstance(attribute_name, str) or not attribute_name.strip():
        raise ValueError("Invalid attribute name")


class AnalyticalAttributePublicationStore:
    """Publish/revoke only attributes belonging to an existing source entity."""

    def __init__(self, metadata_provider):
        self._metadata = metadata_provider

    async def _pool(self):
        await self._metadata.initialize()
        return await self._metadata._get_pool()

    async def publish(self, *, data_source_id: int, entity_id: int, attribute_name: str) -> None:
        _validate(data_source_id, entity_id, attribute_name)
        pool = await self._pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(ATTRIBUTE_DIMENSION_PUBLICATION_DDL)
                    await cursor.execute(
                        """
                        SELECT 1 FROM datapilot_catalog.semantic_attributes a
                        JOIN datapilot_catalog.semantic_entities e ON e.id = a.entity_id
                        WHERE e.data_source_id = %s AND e.id = %s AND a.name = %s
                        """,
                        (data_source_id, entity_id, attribute_name),
                    )
                    if await cursor.fetchone() is None:
                        raise ValueError("Attribute does not belong to datasource entity")
                    await cursor.execute(
                        """
                        INSERT INTO datapilot_catalog.analytical_attribute_publications
                            (data_source_id, entity_id, attribute_name)
                        VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
                        """,
                        (data_source_id, entity_id, attribute_name),
                    )

    async def revoke(self, *, data_source_id: int, entity_id: int, attribute_name: str) -> None:
        _validate(data_source_id, entity_id, attribute_name)
        pool = await self._pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(ATTRIBUTE_DIMENSION_PUBLICATION_DDL)
                    await cursor.execute(
                        """
                        DELETE FROM datapilot_catalog.analytical_attribute_publications
                        WHERE data_source_id = %s AND entity_id = %s AND attribute_name = %s
                        """,
                        (data_source_id, entity_id, attribute_name),
                    )

    async def is_published(self, data_source_id: int, entity_id: int, attribute_name: str) -> bool:
        _validate(data_source_id, entity_id, attribute_name)
        pool = await self._pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(ATTRIBUTE_DIMENSION_PUBLICATION_DDL)
                await cursor.execute(
                    """
                    SELECT 1 FROM datapilot_catalog.analytical_attribute_publications p
                    JOIN datapilot_catalog.semantic_entities e
                      ON e.id = p.entity_id AND e.data_source_id = p.data_source_id
                    JOIN datapilot_catalog.semantic_attributes a
                      ON a.entity_id = e.id AND a.name = p.attribute_name
                    WHERE p.data_source_id = %s AND p.entity_id = %s
                      AND p.attribute_name = %s
                    """,
                    (data_source_id, entity_id, attribute_name),
                )
                return await cursor.fetchone() is not None
