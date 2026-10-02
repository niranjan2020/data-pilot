"""PostgreSQL persistence adapter for the Data Pilot metadata catalog."""

from __future__ import annotations

import json
from typing import Optional

from psycopg.rows import tuple_row
from psycopg_pool import AsyncConnectionPool

from datapilot.core.exceptions import DatabaseConnectionError, MetadataError
from datapilot.domain.interfaces.metadata import MetadataProvider
from datapilot.domain.models import ColumnMetadata, ForeignKeyMetadata, SchemaMetadata, TableMetadata

_CATALOG_DDL = """
CREATE SCHEMA IF NOT EXISTS datapilot_catalog;

CREATE TABLE IF NOT EXISTS datapilot_catalog.data_sources (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    database_name TEXT NOT NULL,
    username TEXT NOT NULL,
    sslmode TEXT NOT NULL DEFAULT 'prefer',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE IF EXISTS datapilot_catalog.schema_snapshots ADD COLUMN IF NOT EXISTS data_source_id BIGINT REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE;

ALTER TABLE IF EXISTS datapilot_catalog.schema_snapshots
    DROP CONSTRAINT IF EXISTS schema_snapshots_schema_name_version_key;

CREATE TABLE IF NOT EXISTS datapilot_catalog.schema_snapshots (
    id BIGSERIAL PRIMARY KEY,
    data_source_id BIGINT REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE,
    schema_name TEXT NOT NULL,
    dialect TEXT NOT NULL,
    version TEXT NOT NULL,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (data_source_id, schema_name, version)
);

CREATE INDEX IF NOT EXISTS ix_datapilot_schema_snapshots_latest
    ON datapilot_catalog.schema_snapshots (data_source_id, schema_name, discovered_at DESC);

CREATE TABLE IF NOT EXISTS datapilot_catalog.tables (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL REFERENCES datapilot_catalog.schema_snapshots(id) ON DELETE CASCADE,
    schema_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    description TEXT,
    UNIQUE (snapshot_id, table_name)
);

CREATE TABLE IF NOT EXISTS datapilot_catalog.columns (
    id BIGSERIAL PRIMARY KEY,
    table_id BIGINT NOT NULL REFERENCES datapilot_catalog.tables(id) ON DELETE CASCADE,
    column_name TEXT NOT NULL,
    data_type TEXT NOT NULL,
    is_nullable BOOLEAN NOT NULL,
    is_primary_key BOOLEAN NOT NULL,
    description TEXT,
    sample_values JSONB NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (table_id, column_name)
);

CREATE TABLE IF NOT EXISTS datapilot_catalog.foreign_keys (
    id BIGSERIAL PRIMARY KEY,
    table_id BIGINT NOT NULL REFERENCES datapilot_catalog.tables(id) ON DELETE CASCADE,
    constrained_column TEXT NOT NULL,
    referenced_table TEXT NOT NULL,
    referenced_column TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_datapilot_tables_snapshot
    ON datapilot_catalog.tables (snapshot_id, table_name);

CREATE INDEX IF NOT EXISTS ix_datapilot_columns_table
    ON datapilot_catalog.columns (table_id, column_name);

CREATE UNIQUE INDEX IF NOT EXISTS ux_datapilot_schema_source_version
    ON datapilot_catalog.schema_snapshots (data_source_id, schema_name, version);

CREATE TABLE IF NOT EXISTS datapilot_catalog.semantic_entities (
    id BIGSERIAL PRIMARY KEY,
    data_source_id BIGINT NOT NULL REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    schema_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    key_column TEXT NOT NULL,
    display_column TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (data_source_id, name)
);

CREATE TABLE IF NOT EXISTS datapilot_catalog.semantic_entity_synonyms (
    entity_id BIGINT NOT NULL REFERENCES datapilot_catalog.semantic_entities(id) ON DELETE CASCADE,
    synonym TEXT NOT NULL,
    PRIMARY KEY (entity_id, synonym)
);

CREATE TABLE IF NOT EXISTS datapilot_catalog.semantic_attributes (
    id BIGSERIAL PRIMARY KEY,
    entity_id BIGINT NOT NULL REFERENCES datapilot_catalog.semantic_entities(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    column_name TEXT NOT NULL,
    operators JSONB NOT NULL DEFAULT '["="]'::jsonb,
    UNIQUE (entity_id, name)
);

CREATE TABLE IF NOT EXISTS datapilot_catalog.semantic_attribute_synonyms (
    attribute_id BIGINT NOT NULL REFERENCES datapilot_catalog.semantic_attributes(id) ON DELETE CASCADE,
    synonym TEXT NOT NULL,
    PRIMARY KEY (attribute_id, synonym)
);

CREATE TABLE IF NOT EXISTS datapilot_catalog.semantic_relationships (
    id BIGSERIAL PRIMARY KEY,
    data_source_id BIGINT NOT NULL REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    from_entity_id BIGINT NOT NULL REFERENCES datapilot_catalog.semantic_entities(id) ON DELETE CASCADE,
    from_column TEXT NOT NULL,
    to_entity_id BIGINT NOT NULL REFERENCES datapilot_catalog.semantic_entities(id) ON DELETE CASCADE,
    to_column TEXT NOT NULL,
    cardinality TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (data_source_id, name)
);

CREATE TABLE IF NOT EXISTS datapilot_catalog.semantic_metrics (
    id BIGSERIAL PRIMARY KEY,
    data_source_id BIGINT NOT NULL REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    entity_id BIGINT NOT NULL REFERENCES datapilot_catalog.semantic_entities(id) ON DELETE CASCADE,
    attribute_name TEXT NOT NULL,
    aggregation TEXT NOT NULL,
    format TEXT NOT NULL DEFAULT 'number',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (data_source_id, name)
);

CREATE TABLE IF NOT EXISTS datapilot_catalog.semantic_metric_synonyms (
    metric_id BIGINT NOT NULL REFERENCES datapilot_catalog.semantic_metrics(id) ON DELETE CASCADE,
    synonym TEXT NOT NULL,
    PRIMARY KEY (metric_id, synonym)
);

CREATE TABLE IF NOT EXISTS datapilot_catalog.semantic_business_rules (
    id BIGSERIAL PRIMARY KEY,
    data_source_id BIGINT NOT NULL REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    rule_type TEXT NOT NULL,
    entity_id BIGINT REFERENCES datapilot_catalog.semantic_entities(id) ON DELETE CASCADE,
    metric_id BIGINT REFERENCES datapilot_catalog.semantic_metrics(id) ON DELETE CASCADE,
    priority INTEGER NOT NULL DEFAULT 100,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (data_source_id, name),
    CHECK (entity_id IS NOT NULL OR metric_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS datapilot_catalog.semantic_business_rule_keywords (
    rule_id BIGINT NOT NULL REFERENCES datapilot_catalog.semantic_business_rules(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    PRIMARY KEY (rule_id, keyword)
);
"""


class PostgreSQLMetadataProvider(MetadataProvider):
    """Persist versioned Data Pilot catalog metadata in PostgreSQL.

    This database is the catalog store, not the customer's query database. For
    local development both may point at the same PostgreSQL instance; production
    deployments can use a separate metadata database without changing the domain.
    """

    def __init__(self, database_url: str, pool_size: int = 3) -> None:
        if not database_url:
            raise DatabaseConnectionError("Metadata PostgreSQL database URL is required")
        if pool_size < 1:
            raise ValueError("pool_size must be at least 1")

        self._database_url = database_url
        self._pool_size = pool_size
        self._pool: Optional[AsyncConnectionPool] = None

    async def _get_pool(self) -> AsyncConnectionPool:
        if self._pool is not None:
            return self._pool
        pool = AsyncConnectionPool(
            conninfo=self._database_url,
            min_size=1,
            max_size=self._pool_size,
            open=False,
            kwargs={"row_factory": tuple_row},
        )
        try:
            await pool.open(wait=True)
        except Exception as exc:  # pragma: no cover - driver-specific
            await pool.close()
            raise DatabaseConnectionError(
                "Unable to connect to metadata PostgreSQL database",
                details={"error_type": type(exc).__name__},
            ) from exc
        self._pool = pool
        return pool

    async def initialize(self) -> None:
        """Create the catalog tables if they do not exist."""
        pool = await self._get_pool()
        try:
            async with pool.connection() as connection:
                async with connection.transaction():
                    async with connection.cursor() as cursor:
                        for statement in _CATALOG_DDL.split(";"):
                            statement = statement.strip()
                            if statement:
                                await cursor.execute(statement)
        except DatabaseConnectionError:
            raise
        except Exception as exc:
            raise MetadataError(
                "Failed to initialize the Data Pilot metadata catalog",
                details={"error_type": type(exc).__name__},
            ) from exc

    async def save_data_source(
        self, *, name: str, provider: str, host: str, port: int,
        database_name: str, username: str, sslmode: str,
    ) -> int:
        """Persist non-secret data-source configuration. Passwords are never stored here."""
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO datapilot_catalog.data_sources
                            (name, provider, host, port, database_name, username, sslmode)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (name) DO UPDATE SET
                            provider = EXCLUDED.provider,
                            host = EXCLUDED.host,
                            port = EXCLUDED.port,
                            database_name = EXCLUDED.database_name,
                            username = EXCLUDED.username,
                            sslmode = EXCLUDED.sslmode,
                            updated_at = NOW()
                        RETURNING id
                        """,
                        (name, provider, host, port, database_name, username, sslmode),
                    )
                    return (await cursor.fetchone())[0]

    async def get_data_source_id(self, name: str) -> Optional[int]:
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT id FROM datapilot_catalog.data_sources WHERE name = %s",
                    (name,),
                )
                row = await cursor.fetchone()
                return row[0] if row else None

    async def list_catalog_tables(self, data_source_id: int) -> list[dict]:
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    WITH latest AS (
                        SELECT DISTINCT ON (schema_name) id
                        FROM datapilot_catalog.schema_snapshots
                        WHERE data_source_id = %s
                        ORDER BY schema_name, discovered_at DESC, id DESC
                    )
                    SELECT t.schema_name, t.table_name,
                           jsonb_agg(
                               jsonb_build_object(
                                   'name', c.column_name,
                                   'data_type', c.data_type,
                                   'is_primary_key', c.is_primary_key
                               )
                               ORDER BY c.column_name
                           )
                    FROM datapilot_catalog.tables t
                    JOIN latest l ON l.id = t.snapshot_id
                    JOIN datapilot_catalog.columns c ON c.table_id = t.id
                    GROUP BY t.schema_name, t.table_name
                    ORDER BY t.schema_name, t.table_name
                    """,
                    (data_source_id,),
                )
                return [
                    {"schema_name": row[0], "table_name": row[1], "columns": row[2] or []}
                    for row in await cursor.fetchall()
                ]

    async def save_semantic_entity(
        self, *, data_source_id: int, name: str, description: Optional[str],
        schema_name: str, table_name: str, key_column: str,
        display_column: Optional[str], synonyms: list[str],
        attributes: list[dict],
    ) -> int:
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO datapilot_catalog.semantic_entities
                            (data_source_id, name, description, schema_name, table_name,
                             key_column, display_column)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (data_source_id, name) DO UPDATE SET
                            description = EXCLUDED.description,
                            schema_name = EXCLUDED.schema_name,
                            table_name = EXCLUDED.table_name,
                            key_column = EXCLUDED.key_column,
                            display_column = EXCLUDED.display_column,
                            updated_at = NOW()
                        RETURNING id
                        """,
                        (data_source_id, name, description, schema_name, table_name,
                         key_column, display_column),
                    )
                    entity_id = (await cursor.fetchone())[0]

                    await cursor.execute(
                        "DELETE FROM datapilot_catalog.semantic_entity_synonyms WHERE entity_id = %s",
                        (entity_id,),
                    )
                    for synonym in sorted({s.strip() for s in synonyms if s.strip()}):
                        await cursor.execute(
                            """
                            INSERT INTO datapilot_catalog.semantic_entity_synonyms
                                (entity_id, synonym)
                            VALUES (%s, %s)
                            """,
                            (entity_id, synonym),
                        )

                    await cursor.execute(
                        "DELETE FROM datapilot_catalog.semantic_attributes WHERE entity_id = %s",
                        (entity_id,),
                    )
                    for attribute in attributes:
                        await cursor.execute(
                            """
                            INSERT INTO datapilot_catalog.semantic_attributes
                                (entity_id, name, description, column_name, operators)
                            VALUES (%s, %s, %s, %s, %s::jsonb)
                            RETURNING id
                            """,
                            (
                                entity_id,
                                attribute["name"],
                                attribute.get("description"),
                                attribute["column_name"],
                                json.dumps(attribute.get("operators") or ["="]),
                            ),
                        )
                        attribute_id = (await cursor.fetchone())[0]
                        for synonym in sorted({
                            s.strip() for s in attribute.get("synonyms", []) if s.strip()
                        }):
                            await cursor.execute(
                                """
                                INSERT INTO datapilot_catalog.semantic_attribute_synonyms
                                    (attribute_id, synonym)
                                VALUES (%s, %s)
                                """,
                                (attribute_id, synonym),
                            )
                    return entity_id

    async def list_semantic_entities(self, data_source_id: int) -> list[dict]:
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT e.id, e.name, e.description, e.schema_name, e.table_name,
                           e.key_column, e.display_column,
                           COALESCE(
                               (SELECT jsonb_agg(s.synonym ORDER BY s.synonym)
                                FROM datapilot_catalog.semantic_entity_synonyms s
                                WHERE s.entity_id = e.id),
                               '[]'::jsonb
                           )
                    FROM datapilot_catalog.semantic_entities e
                    WHERE e.data_source_id = %s
                    ORDER BY e.name
                    """,
                    (data_source_id,),
                )
                entity_rows = await cursor.fetchall()
                entities = []
                for row in entity_rows:
                    await cursor.execute(
                        """
                        SELECT a.id, a.name, a.description, a.column_name, a.operators
                        FROM datapilot_catalog.semantic_attributes a
                        WHERE a.entity_id = %s
                        ORDER BY a.name
                        """,
                        (row[0],),
                    )
                    attributes = []
                    for attribute in await cursor.fetchall():
                        await cursor.execute(
                            """
                            SELECT synonym
                            FROM datapilot_catalog.semantic_attribute_synonyms
                            WHERE attribute_id = %s
                            ORDER BY synonym
                            """,
                            (attribute[0],),
                        )
                        attributes.append({
                            "name": attribute[1],
                            "description": attribute[2],
                            "column_name": attribute[3],
                            "operators": attribute[4] or ["="],
                            "synonyms": [s[0] for s in await cursor.fetchall()],
                        })
                    entities.append({
                        "id": row[0],
                        "name": row[1],
                        "description": row[2],
                        "schema_name": row[3],
                        "table_name": row[4],
                        "key_column": row[5],
                        "display_column": row[6],
                        "synonyms": row[7] or [],
                        "attributes": attributes,
                    })
                return entities

    async def save_semantic_relationship(
        self, *, data_source_id: int, name: str, from_entity_id: int,
        from_column: str, to_entity_id: int, to_column: str,
        cardinality: str, description: Optional[str],
    ) -> int:
        await self.initialize()
        if from_entity_id == to_entity_id:
            raise MetadataError("A semantic relationship must connect two different entities")
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT COUNT(*) FROM datapilot_catalog.semantic_entities
                        WHERE data_source_id = %s AND id = ANY(%s)
                        """,
                        (data_source_id, [from_entity_id, to_entity_id]),
                    )
                    if (await cursor.fetchone())[0] != 2:
                        raise MetadataError("Relationship entities must belong to the selected data source")
                    await cursor.execute(
                        """
                        INSERT INTO datapilot_catalog.semantic_relationships
                            (data_source_id, name, from_entity_id, from_column,
                             to_entity_id, to_column, cardinality, description)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (data_source_id, name) DO UPDATE SET
                            from_entity_id = EXCLUDED.from_entity_id,
                            from_column = EXCLUDED.from_column,
                            to_entity_id = EXCLUDED.to_entity_id,
                            to_column = EXCLUDED.to_column,
                            cardinality = EXCLUDED.cardinality,
                            description = EXCLUDED.description,
                            updated_at = NOW()
                        RETURNING id
                        """,
                        (data_source_id, name, from_entity_id, from_column,
                         to_entity_id, to_column, cardinality, description),
                    )
                    return (await cursor.fetchone())[0]

    async def list_semantic_relationships(self, data_source_id: int) -> list[dict]:
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT r.id, r.name, r.from_entity_id, fe.name, r.from_column,
                           r.to_entity_id, te.name, r.to_column, r.cardinality,
                           r.description
                    FROM datapilot_catalog.semantic_relationships r
                    JOIN datapilot_catalog.semantic_entities fe ON fe.id = r.from_entity_id
                    JOIN datapilot_catalog.semantic_entities te ON te.id = r.to_entity_id
                    WHERE r.data_source_id = %s
                    ORDER BY r.name
                    """,
                    (data_source_id,),
                )
                return [{
                    "id": row[0], "name": row[1],
                    "from_entity_id": row[2], "from_entity_name": row[3],
                    "from_column": row[4],
                    "to_entity_id": row[5], "to_entity_name": row[6],
                    "to_column": row[7], "cardinality": row[8],
                    "description": row[9],
                } for row in await cursor.fetchall()]

    async def save_semantic_metric(
        self, *, data_source_id: int, name: str, description: Optional[str],
        entity_id: int, attribute_name: str, aggregation: str,
        format: str, synonyms: list[str],
    ) -> int:
        await self.initialize()
        allowed = {"sum", "count", "count_distinct", "avg", "min", "max"}
        if aggregation not in allowed:
            raise MetadataError("Unsupported metric aggregation")
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT COUNT(*) FROM datapilot_catalog.semantic_attributes a
                        JOIN datapilot_catalog.semantic_entities e ON e.id = a.entity_id
                        WHERE e.data_source_id = %s AND e.id = %s AND a.name = %s
                        """,
                        (data_source_id, entity_id, attribute_name),
                    )
                    if (await cursor.fetchone())[0] != 1:
                        raise MetadataError("Metric attribute must belong to the selected entity")
                    await cursor.execute(
                        """
                        INSERT INTO datapilot_catalog.semantic_metrics
                            (data_source_id, name, description, entity_id,
                             attribute_name, aggregation, format)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (data_source_id, name) DO UPDATE SET
                            description = EXCLUDED.description,
                            entity_id = EXCLUDED.entity_id,
                            attribute_name = EXCLUDED.attribute_name,
                            aggregation = EXCLUDED.aggregation,
                            format = EXCLUDED.format,
                            updated_at = NOW()
                        RETURNING id
                        """,
                        (data_source_id, name, description, entity_id,
                         attribute_name, aggregation, format),
                    )
                    metric_id = (await cursor.fetchone())[0]
                    await cursor.execute(
                        "DELETE FROM datapilot_catalog.semantic_metric_synonyms WHERE metric_id = %s",
                        (metric_id,),
                    )
                    for synonym in sorted({s.strip() for s in synonyms if s.strip()}):
                        await cursor.execute(
                            "INSERT INTO datapilot_catalog.semantic_metric_synonyms (metric_id, synonym) VALUES (%s, %s)",
                            (metric_id, synonym),
                        )
                    return metric_id

    async def list_semantic_metrics(self, data_source_id: int) -> list[dict]:
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT m.id, m.name, m.description, m.entity_id, e.name,
                           m.attribute_name, m.aggregation, m.format,
                           COALESCE(
                               (SELECT jsonb_agg(s.synonym ORDER BY s.synonym)
                                FROM datapilot_catalog.semantic_metric_synonyms s
                                WHERE s.metric_id = m.id),
                               '[]'::jsonb
                           )
                    FROM datapilot_catalog.semantic_metrics m
                    JOIN datapilot_catalog.semantic_entities e ON e.id = m.entity_id
                    WHERE m.data_source_id = %s
                    ORDER BY m.name
                    """,
                    (data_source_id,),
                )
                return [{
                    "id": row[0], "name": row[1], "description": row[2],
                    "entity_id": row[3], "entity_name": row[4],
                    "attribute_name": row[5], "aggregation": row[6],
                    "format": row[7], "synonyms": row[8] or [],
                } for row in await cursor.fetchall()]

    async def save_business_rule(
        self, *, data_source_id: int, name: str, description: str,
        rule_type: str, entity_id: Optional[int], metric_id: Optional[int],
        priority: int, enabled: bool, keywords: list[str],
    ) -> int:
        await self.initialize()
        allowed = {"definition", "filter", "calculation", "interpretation"}
        if rule_type not in allowed:
            raise MetadataError("Unsupported business rule type")
        if entity_id is None and metric_id is None:
            raise MetadataError("Business rule must target an entity or metric")
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    if entity_id is not None:
                        await cursor.execute(
                            "SELECT 1 FROM datapilot_catalog.semantic_entities WHERE id=%s AND data_source_id=%s",
                            (entity_id, data_source_id),
                        )
                        if await cursor.fetchone() is None:
                            raise MetadataError("Business rule entity does not belong to the selected data source")
                    if metric_id is not None:
                        await cursor.execute(
                            "SELECT 1 FROM datapilot_catalog.semantic_metrics WHERE id=%s AND data_source_id=%s",
                            (metric_id, data_source_id),
                        )
                        if await cursor.fetchone() is None:
                            raise MetadataError("Business rule metric does not belong to the selected data source")
                    await cursor.execute(
                        """
                        INSERT INTO datapilot_catalog.semantic_business_rules
                            (data_source_id, name, description, rule_type, entity_id,
                             metric_id, priority, enabled)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (data_source_id, name) DO UPDATE SET
                            description=EXCLUDED.description, rule_type=EXCLUDED.rule_type,
                            entity_id=EXCLUDED.entity_id, metric_id=EXCLUDED.metric_id,
                            priority=EXCLUDED.priority, enabled=EXCLUDED.enabled,
                            updated_at=NOW()
                        RETURNING id
                        """,
                        (data_source_id,name,description,rule_type,entity_id,metric_id,priority,enabled),
                    )
                    rule_id=(await cursor.fetchone())[0]
                    await cursor.execute(
                        "DELETE FROM datapilot_catalog.semantic_business_rule_keywords WHERE rule_id=%s",
                        (rule_id,),
                    )
                    for keyword in sorted({k.strip() for k in keywords if k.strip()}):
                        await cursor.execute(
                            "INSERT INTO datapilot_catalog.semantic_business_rule_keywords (rule_id,keyword) VALUES (%s,%s)",
                            (rule_id,keyword),
                        )
                    return rule_id

    async def list_business_rules(self, data_source_id: int) -> list[dict]:
        await self.initialize()
        pool=await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT r.id,r.name,r.description,r.rule_type,r.entity_id,e.name,
                           r.metric_id,m.name,r.priority,r.enabled,
                           COALESCE((SELECT jsonb_agg(k.keyword ORDER BY k.keyword)
                             FROM datapilot_catalog.semantic_business_rule_keywords k
                             WHERE k.rule_id=r.id),'[]'::jsonb)
                    FROM datapilot_catalog.semantic_business_rules r
                    LEFT JOIN datapilot_catalog.semantic_entities e ON e.id=r.entity_id
                    LEFT JOIN datapilot_catalog.semantic_metrics m ON m.id=r.metric_id
                    WHERE r.data_source_id=%s ORDER BY r.priority,r.name
                    """,
                    (data_source_id,),
                )
                return [{
                    "id":x[0],"name":x[1],"description":x[2],"rule_type":x[3],
                    "entity_id":x[4],"entity_name":x[5],"metric_id":x[6],"metric_name":x[7],
                    "priority":x[8],"enabled":x[9],"keywords":x[10] or [],
                } for x in await cursor.fetchall()]

    @staticmethod
    def _schema_name(schema: SchemaMetadata) -> str:
        if schema.schema_name:
            return schema.schema_name
        names = {table.schema_name for table in schema.tables if table.schema_name}
        if len(names) == 1:
            return next(iter(names))
        return "public"

    async def save_schema(self, schema: SchemaMetadata, data_source_id: Optional[int] = None) -> None:
        if not schema.version:
            raise MetadataError("Schema version is required before persisting metadata")

        pool = await self._get_pool()
        schema_name = self._schema_name(schema)
        try:
            async with pool.connection() as connection:
                async with connection.transaction():
                    async with connection.cursor() as cursor:
                        for statement in _CATALOG_DDL.split(";"):
                            statement = statement.strip()
                            if statement:
                                await cursor.execute(statement)
                        await cursor.execute(
                            """
                            SELECT id FROM datapilot_catalog.schema_snapshots
                            WHERE data_source_id IS NOT DISTINCT FROM %s
                              AND schema_name = %s AND version = %s
                            ORDER BY id DESC LIMIT 1
                            """,
                            (data_source_id, schema_name, schema.version),
                        )
                        row = await cursor.fetchone()
                        if row is None:
                            await cursor.execute(
                                """
                                INSERT INTO datapilot_catalog.schema_snapshots
                                    (data_source_id, schema_name, dialect, version)
                                VALUES (%s, %s, %s, %s)
                                RETURNING id
                                """,
                                (data_source_id, schema_name, schema.dialect, schema.version),
                            )
                            row = await cursor.fetchone()
                        snapshot_id = row[0]

                        for table in schema.tables:
                            await cursor.execute(
                                """
                                INSERT INTO datapilot_catalog.tables
                                    (snapshot_id, schema_name, table_name, description)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (snapshot_id, table_name)
                                DO UPDATE SET description = EXCLUDED.description
                                RETURNING id
                                """,
                                (snapshot_id, table.schema_name or schema_name, table.name, table.description),
                            )
                            table_id = (await cursor.fetchone())[0]

                            await cursor.execute(
                                "DELETE FROM datapilot_catalog.columns WHERE table_id = %s", (table_id,)
                            )
                            await cursor.execute(
                                "DELETE FROM datapilot_catalog.foreign_keys WHERE table_id = %s", (table_id,)
                            )

                            for column in table.columns:
                                await cursor.execute(
                                    """
                                    INSERT INTO datapilot_catalog.columns
                                        (table_id, column_name, data_type, is_nullable,
                                         is_primary_key, description, sample_values)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                                    """,
                                    (
                                        table_id,
                                        column.name,
                                        column.data_type,
                                        column.is_nullable,
                                        column.is_primary_key,
                                        column.description,
                                        json.dumps(column.sample_values),
                                    ),
                                )

                            for foreign_key in table.foreign_keys:
                                await cursor.execute(
                                    """
                                    INSERT INTO datapilot_catalog.foreign_keys
                                        (table_id, constrained_column, referenced_table, referenced_column)
                                    VALUES (%s, %s, %s, %s)
                                    """,
                                    (
                                        table_id,
                                        foreign_key.constrained_column,
                                        foreign_key.referenced_table,
                                        foreign_key.referenced_column,
                                    ),
                                )
        except MetadataError:
            raise
        except Exception as exc:
            raise MetadataError(
                "Failed to persist Data Pilot schema metadata",
                details={"error_type": type(exc).__name__, "schema": schema_name},
            ) from exc

    async def get_schema(self, schema_name: Optional[str] = None) -> Optional[SchemaMetadata]:
        pool = await self._get_pool()
        try:
            async with pool.connection() as connection:
                async with connection.cursor() as cursor:
                    if schema_name:
                        await cursor.execute(
                            """
                            SELECT id, schema_name, dialect, version
                            FROM datapilot_catalog.schema_snapshots
                            WHERE schema_name = %s
                            ORDER BY discovered_at DESC, id DESC
                            LIMIT 1
                            """,
                            (schema_name,),
                        )
                    else:
                        await cursor.execute(
                            """
                            SELECT id, schema_name, dialect, version
                            FROM datapilot_catalog.schema_snapshots
                            ORDER BY discovered_at DESC, id DESC
                            LIMIT 1
                            """
                        )
                    snapshot = await cursor.fetchone()
                    if snapshot is None:
                        return None
                    return await self._load_snapshot(cursor, snapshot)
        except Exception as exc:
            raise MetadataError(
                "Failed to load Data Pilot schema metadata",
                details={"error_type": type(exc).__name__, "schema": schema_name},
            ) from exc

    async def get_table(self, table_name: str, schema_name: Optional[str] = None) -> Optional[TableMetadata]:
        schema = await self.get_schema(schema_name)
        return schema.get_table(table_name) if schema else None

    async def list_tables(self, schema_name: Optional[str] = None) -> list[str]:
        schema = await self.get_schema(schema_name)
        return [table.name for table in schema.tables] if schema else []

    @staticmethod
    async def _load_snapshot(cursor, snapshot) -> SchemaMetadata:
        snapshot_id, schema_name, dialect, version = snapshot
        await cursor.execute(
            """
            SELECT id, table_name, description FROM datapilot_catalog.tables
            WHERE snapshot_id = %s ORDER BY table_name
            """,
            (snapshot_id,),
        )
        table_rows = await cursor.fetchall()
        tables = {
            row[0]: TableMetadata(name=row[1], schema_name=schema_name, description=row[2])
            for row in table_rows
        }
        if not tables:
            return SchemaMetadata(schema_name=schema_name, dialect=dialect, version=version)

        table_ids = tuple(tables)
        await cursor.execute(
            """
            SELECT table_id, column_name, data_type, is_nullable, is_primary_key,
                   description, sample_values
            FROM datapilot_catalog.columns
            WHERE table_id = ANY(%s)
            ORDER BY table_id, column_name
            """,
            (list(table_ids),),
        )
        for row in await cursor.fetchall():
            table = tables[row[0]]
            column = ColumnMetadata(
                name=row[1], data_type=row[2], is_nullable=row[3],
                is_primary_key=row[4], description=row[5],
                sample_values=row[6] or [],
            )
            table.columns.append(column)
            if column.is_primary_key:
                table.primary_keys.append(column.name)

        await cursor.execute(
            """
            SELECT table_id, constrained_column, referenced_table, referenced_column
            FROM datapilot_catalog.foreign_keys
            WHERE table_id = ANY(%s)
            ORDER BY table_id, constrained_column
            """,
            (list(table_ids),),
        )
        for row in await cursor.fetchall():
            tables[row[0]].foreign_keys.append(
                ForeignKeyMetadata(
                    constrained_column=row[1], referenced_table=row[2], referenced_column=row[3]
                )
            )

        return SchemaMetadata(
            schema_name=schema_name,
            tables=list(tables.values()),
            dialect=dialect,
            version=version,
        )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def __aenter__(self) -> "PostgreSQLMetadataProvider":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
