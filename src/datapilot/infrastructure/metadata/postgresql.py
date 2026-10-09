"""PostgreSQL persistence adapter for the Data Pilot metadata catalog."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from psycopg.rows import tuple_row
from psycopg_pool import AsyncConnectionPool

from datapilot.core.exceptions import DatabaseConnectionError, MetadataError
from datapilot.domain.interfaces.metadata import MetadataProvider
from datapilot.domain.interfaces.ai_configuration import AIProviderConfiguration, AIProviderKind
from datapilot.domain.models import ColumnMetadata, ForeignKeyMetadata, SchemaMetadata, TableMetadata

_CATALOG_DDL = """
CREATE SCHEMA IF NOT EXISTS datapilot_catalog;

CREATE TABLE IF NOT EXISTS datapilot_catalog.ai_provider_configuration (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    endpoint TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS datapilot_catalog.setup_state (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    ai_provider_ready BOOLEAN NOT NULL DEFAULT FALSE,
    data_source_ready BOOLEAN NOT NULL DEFAULT FALSE,
    data_selection_ready BOOLEAN NOT NULL DEFAULT FALSE,
    semantic_model_ready BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO datapilot_catalog.setup_state (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;

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

ALTER TABLE datapilot_catalog.setup_state ADD COLUMN IF NOT EXISTS active_data_source_id BIGINT;

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

CREATE TABLE IF NOT EXISTS datapilot_catalog.discovered_unique_constraints (
    table_id BIGINT NOT NULL REFERENCES datapilot_catalog.tables(id) ON DELETE CASCADE,
    constraint_name TEXT NOT NULL,
    columns JSONB NOT NULL,
    is_primary_key BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (table_id, constraint_name)
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

CREATE TABLE IF NOT EXISTS datapilot_catalog.semantic_datasets (
    id BIGSERIAL PRIMARY KEY,
    data_source_id BIGINT NOT NULL REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE,
    schema_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    description TEXT,
    business_meaning TEXT,
    grain TEXT,
    identity_semantics TEXT,
    use_cases JSONB NOT NULL DEFAULT '[]'::jsonb,
    query_constraints JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (data_source_id, schema_name, table_name)
);

CREATE TABLE IF NOT EXISTS datapilot_catalog.semantic_dataset_aliases (
    dataset_id BIGINT NOT NULL REFERENCES datapilot_catalog.semantic_datasets(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    PRIMARY KEY (dataset_id, alias)
);

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

CREATE TABLE IF NOT EXISTS datapilot_catalog.semantic_attribute_values (
    attribute_id BIGINT NOT NULL REFERENCES datapilot_catalog.semantic_attributes(id) ON DELETE CASCADE,
    canonical_value TEXT NOT NULL,
    synonyms JSONB NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (attribute_id, canonical_value)
);

CREATE TABLE IF NOT EXISTS datapilot_catalog.semantic_time_dimensions (
    id BIGSERIAL PRIMARY KEY,
    data_source_id BIGINT NOT NULL REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE,
    entity_id BIGINT NOT NULL REFERENCES datapilot_catalog.semantic_entities(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    column_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'event_time',
    grain TEXT NOT NULL DEFAULT 'day',
    timezone TEXT NOT NULL DEFAULT 'UTC',
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    synonyms JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (data_source_id, name)
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

ALTER TABLE datapilot_catalog.semantic_relationships
    ADD COLUMN IF NOT EXISTS join_policy TEXT NOT NULL DEFAULT 'unconfigured';

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

ALTER TABLE IF EXISTS datapilot_catalog.semantic_metrics
    ALTER COLUMN attribute_name DROP NOT NULL;

ALTER TABLE IF EXISTS datapilot_catalog.semantic_metrics
    ADD COLUMN IF NOT EXISTS calculation_expression TEXT;

CREATE TABLE IF NOT EXISTS datapilot_catalog.semantic_ranking_rules (
    id BIGSERIAL PRIMARY KEY,
    data_source_id BIGINT NOT NULL REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE,
    entity_id BIGINT NOT NULL REFERENCES datapilot_catalog.semantic_entities(id) ON DELETE CASCADE,
    dimension_attribute_name TEXT NOT NULL,
    metric_id BIGINT NOT NULL REFERENCES datapilot_catalog.semantic_metrics(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    default_top_n INTEGER NOT NULL DEFAULT 10 CHECK (default_top_n BETWEEN 1 AND 100),
    direction TEXT NOT NULL DEFAULT 'desc' CHECK (direction IN ('asc', 'desc')),
    scope TEXT NOT NULL DEFAULT 'global' CHECK (scope IN ('global', 'per_group')),
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (data_source_id, entity_id, name)
);

CREATE UNIQUE INDEX IF NOT EXISTS semantic_ranking_one_default_per_entity
    ON datapilot_catalog.semantic_ranking_rules(data_source_id, entity_id)
    WHERE is_default;

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
        self._initialized = False
        self._initialize_lock = asyncio.Lock()

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
        """Initialize the catalog once, serializing DDL across API workers."""
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            pool = await self._get_pool()
            try:
                async with pool.connection() as connection:
                    async with connection.transaction():
                        async with connection.cursor() as cursor:
                            # Transaction-scoped advisory lock coordinates separate
                            # provider instances/processes using the same database.
                            await cursor.execute(
                                "SELECT pg_advisory_xact_lock(1178946124, 20261008)"
                            )
                            for statement in _CATALOG_DDL.split(";"):
                                statement = statement.strip()
                                if statement:
                                    await cursor.execute(statement)
                self._initialized = True
            except DatabaseConnectionError:
                raise
            except Exception as exc:
                raise MetadataError(
                    "Failed to initialize the Data Pilot metadata catalog",
                    details={"error_type": type(exc).__name__},
                ) from exc

    async def get_ai_provider_configuration(self) -> Optional[AIProviderConfiguration]:
        """Return persisted non-secret AI provider configuration."""
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT provider, model, endpoint FROM datapilot_catalog.ai_provider_configuration WHERE id = 1"
                )
                row = await cursor.fetchone()
                if not row:
                    return None
                return AIProviderConfiguration(
                    provider=AIProviderKind(row[0]),
                    model=row[1],
                    endpoint=row[2],
                    configured=True,
                    credential_configured=False,
                )

    async def save_ai_provider_configuration(
        self, configuration: AIProviderConfiguration
    ) -> AIProviderConfiguration:
        """Persist only provider configuration; credential material is never accepted."""
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """INSERT INTO datapilot_catalog.ai_provider_configuration
                               (id, provider, model, endpoint)
                           VALUES (1, %s, %s, %s)
                           ON CONFLICT (id) DO UPDATE SET
                               provider = EXCLUDED.provider,
                               model = EXCLUDED.model,
                               endpoint = EXCLUDED.endpoint,
                               updated_at = NOW()""",
                        (
                            configuration.provider.value,
                            configuration.model,
                            configuration.endpoint,
                        ),
                    )
        return configuration.model_copy(update={"configured": True, "credential_configured": False})

    async def get_setup_facts(self) -> dict[str, bool]:
        """Read persisted non-secret onboarding readiness facts."""
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """SELECT ai_provider_ready, data_source_ready,
                              data_selection_ready, semantic_model_ready
                       FROM datapilot_catalog.setup_state WHERE id = 1"""
                )
                row = await cursor.fetchone()
                return {
                    "ai_provider_ready": bool(row[0]),
                    "data_source_ready": bool(row[1]),
                    "data_selection_ready": bool(row[2]),
                    "semantic_model_ready": bool(row[3]),
                }

    async def update_setup_facts(self, **facts: bool) -> dict[str, bool]:
        """Persist an explicit subset of onboarding readiness facts."""
        allowed = {
            "ai_provider_ready", "data_source_ready",
            "data_selection_ready", "semantic_model_ready",
        }
        unknown = set(facts) - allowed
        if unknown:
            raise ValueError(f"Unknown setup facts: {sorted(unknown)}")
        if not facts:
            return await self.get_setup_facts()
        await self.initialize()
        assignments = ", ".join(f"{name} = %s" for name in facts)
        values = [bool(value) for value in facts.values()]
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        f"UPDATE datapilot_catalog.setup_state SET {assignments}, updated_at = NOW() WHERE id = 1",
                        values,
                    )
        return await self.get_setup_facts()

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

    async def update_data_source_username(self, source_id: int, username: str) -> None:
        """Update the login identity without changing the datasource target."""
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        "UPDATE datapilot_catalog.data_sources SET username = %s, updated_at = NOW() WHERE id = %s",
                        (username, source_id),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError("Saved datasource not found")

    async def set_active_data_source_id(self, source_id: int) -> None:
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "UPDATE datapilot_catalog.setup_state SET active_data_source_id = %s, updated_at = NOW() WHERE id = 1",
                    (source_id,),
                )

    async def get_active_data_source_id(self) -> Optional[int]:
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT active_data_source_id FROM datapilot_catalog.setup_state WHERE id = 1"
                )
                row = await cursor.fetchone()
                if row and row[0] is not None:
                    return row[0]
                # Upgrade path for existing single-datasource local installations.
                await cursor.execute("SELECT id FROM datapilot_catalog.data_sources ORDER BY id LIMIT 2")
                candidates = await cursor.fetchall()
                return candidates[0][0] if len(candidates) == 1 else None

    async def list_saved_data_sources(self) -> list[dict]:
        """Non-secret saved datasource identities for explicit onboarding recovery."""
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT id, name, provider FROM datapilot_catalog.data_sources ORDER BY updated_at DESC, id DESC"
                )
                return [{"id": row[0], "name": row[1], "provider": row[2]} for row in await cursor.fetchall()]

    async def get_data_source(self, source_id: int) -> Optional[dict]:
        """Retrieve non-secret connection metadata for an explicitly selected source."""
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """SELECT id, name, provider, host, port, database_name, username, sslmode
                       FROM datapilot_catalog.data_sources WHERE id = %s""",
                    (source_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                keys = ("id", "name", "provider", "host", "port", "database", "username", "sslmode")
                return dict(zip(keys, row))

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
                           COALESCE((
                               SELECT jsonb_agg(jsonb_build_object(
                                   'name', uq.constraint_name,
                                   'columns', uq.columns,
                                   'is_primary_key', uq.is_primary_key
                               ) ORDER BY uq.constraint_name)
                               FROM datapilot_catalog.discovered_unique_constraints uq
                               WHERE uq.table_id = t.id
                           ), '[]'::jsonb) AS unique_constraints,
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
                    GROUP BY t.id, t.schema_name, t.table_name
                    ORDER BY t.schema_name, t.table_name
                    """,
                    (data_source_id,),
                )
                return [
                    {"schema_name": row[0], "table_name": row[1], "unique_constraints": row[2] or [], "columns": row[3] or []}
                    for row in await cursor.fetchall()
                ]

    async def list_reviewed_relationships(self, data_source_id: int) -> list[dict]:
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("""
                    CREATE TABLE IF NOT EXISTS datapilot_catalog.reviewed_relationships (
                        data_source_id BIGINT NOT NULL REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE,
                        from_schema TEXT NOT NULL, from_table TEXT NOT NULL, from_column TEXT NOT NULL,
                        to_schema TEXT NOT NULL, to_table TEXT NOT NULL, to_column TEXT NOT NULL,
                        cardinality TEXT NOT NULL, review_status TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        join_policy TEXT NOT NULL DEFAULT 'unconfigured',
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (data_source_id, from_schema, from_table, from_column, to_schema, to_table, to_column)
                    )""")
                await cursor.execute("""
                    ALTER TABLE datapilot_catalog.reviewed_relationships
                    ADD COLUMN IF NOT EXISTS join_policy TEXT NOT NULL DEFAULT 'unconfigured'
                """)
                await cursor.execute("""
                    SELECT from_schema, from_table, from_column, to_schema, to_table,
                           to_column, cardinality, review_status, description, join_policy
                    FROM datapilot_catalog.reviewed_relationships
                    WHERE data_source_id = %s ORDER BY from_schema, from_table, from_column
                """, (data_source_id,))
                return [dict(zip(("from_schema","from_table","from_column","to_schema","to_table",
                                  "to_column","cardinality","review_status","description","join_policy"), row))
                        for row in await cursor.fetchall()]

    async def save_reviewed_relationship(self, data_source_id: int, relationship: dict) -> None:
        await self.list_reviewed_relationships(data_source_id)
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("""
                    CREATE TABLE IF NOT EXISTS datapilot_catalog.relationship_verifications (
                        data_source_id BIGINT NOT NULL REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE,
                        from_schema TEXT NOT NULL, from_table TEXT NOT NULL, from_column TEXT NOT NULL,
                        to_schema TEXT NOT NULL, to_table TEXT NOT NULL, to_column TEXT NOT NULL,
                        review_fingerprint TEXT NOT NULL,
                        evidence JSONB NOT NULL,
                        verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (data_source_id, from_schema, from_table, from_column,
                                     to_schema, to_table, to_column)
                    )
                """)
                await cursor.execute("""
                    INSERT INTO datapilot_catalog.reviewed_relationships
                        (data_source_id, from_schema, from_table, from_column, to_schema,
                         to_table, to_column, cardinality, review_status, description, join_policy)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (data_source_id, from_schema, from_table, from_column,
                                 to_schema, to_table, to_column)
                    DO UPDATE SET cardinality=EXCLUDED.cardinality,
                                  review_status=EXCLUDED.review_status,
                                  description=EXCLUDED.description,
                                  join_policy=EXCLUDED.join_policy, updated_at=NOW()
                """, (data_source_id, relationship["from_schema"], relationship["from_table"],
                      relationship["from_column"], relationship["to_schema"], relationship["to_table"],
                      relationship["to_column"], relationship["cardinality"],
                      relationship["review_status"], relationship["description"], relationship.get("join_policy", "unconfigured")))
                await cursor.execute("""
                    CREATE TABLE IF NOT EXISTS datapilot_catalog.relationship_publications (
                        data_source_id BIGINT NOT NULL REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE,
                        from_schema TEXT NOT NULL, from_table TEXT NOT NULL, from_column TEXT NOT NULL,
                        to_schema TEXT NOT NULL, to_table TEXT NOT NULL, to_column TEXT NOT NULL,
                        review_fingerprint TEXT NOT NULL, verification_fingerprint TEXT NOT NULL,
                        published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (data_source_id, from_schema, from_table, from_column,
                                     to_schema, to_table, to_column)
                    )
                """)
                await cursor.execute("""
                    DELETE FROM datapilot_catalog.relationship_publications
                    WHERE data_source_id=%s AND from_schema=%s AND from_table=%s
                      AND from_column=%s AND to_schema=%s AND to_table=%s AND to_column=%s
                """, (data_source_id, relationship["from_schema"], relationship["from_table"],
                      relationship["from_column"], relationship["to_schema"],
                      relationship["to_table"], relationship["to_column"]))
                await cursor.execute("""
                    DELETE FROM datapilot_catalog.relationship_verifications
                    WHERE data_source_id=%s AND from_schema=%s AND from_table=%s
                      AND from_column=%s AND to_schema=%s AND to_table=%s AND to_column=%s
                """, (data_source_id, relationship["from_schema"], relationship["from_table"],
                      relationship["from_column"], relationship["to_schema"],
                      relationship["to_table"], relationship["to_column"]))

    async def save_relationship_verification(
        self, data_source_id: int, review: dict, evidence: dict
    ) -> bool:
        """Persist evidence only while the reviewed contract is unchanged.

        The row lock serializes verification writes with review updates; a
        changed review cannot reuse an earlier verification fingerprint.
        """
        from datapilot.application.relationship_evidence import review_fingerprint
        await self.list_reviewed_relationships(data_source_id)
        pool = await self._get_pool()
        keys = ("from_schema", "from_table", "from_column",
                "to_schema", "to_table", "to_column")
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("""
                    CREATE TABLE IF NOT EXISTS datapilot_catalog.relationship_verifications (
                        data_source_id BIGINT NOT NULL REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE,
                        from_schema TEXT NOT NULL, from_table TEXT NOT NULL, from_column TEXT NOT NULL,
                        to_schema TEXT NOT NULL, to_table TEXT NOT NULL, to_column TEXT NOT NULL,
                        review_fingerprint TEXT NOT NULL,
                        evidence JSONB NOT NULL,
                        verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (data_source_id, from_schema, from_table, from_column,
                                     to_schema, to_table, to_column)
                    )
                """)
                await cursor.execute("""
                    SELECT cardinality, review_status, join_policy
                    FROM datapilot_catalog.reviewed_relationships
                    WHERE data_source_id=%s AND from_schema=%s AND from_table=%s
                      AND from_column=%s AND to_schema=%s AND to_table=%s AND to_column=%s
                    FOR UPDATE
                """, (data_source_id, *(review[k] for k in keys)))
                current = await cursor.fetchone()
                if current is None:
                    return False
                persisted = {**{k: review[k] for k in keys},
                             "cardinality": current[0],
                             "review_status": current[1],
                             "join_policy": current[2]}
                fingerprint = review_fingerprint(persisted)
                if fingerprint != review_fingerprint(review):
                    return False
                # Reverification changes the evidence generation: revoke any
                # prior publication atomically before writing replacement proof.
                await cursor.execute("""
                    CREATE TABLE IF NOT EXISTS datapilot_catalog.relationship_publications (
                        data_source_id BIGINT NOT NULL REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE,
                        from_schema TEXT NOT NULL, from_table TEXT NOT NULL, from_column TEXT NOT NULL,
                        to_schema TEXT NOT NULL, to_table TEXT NOT NULL, to_column TEXT NOT NULL,
                        review_fingerprint TEXT NOT NULL, verification_fingerprint TEXT NOT NULL,
                        published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (data_source_id, from_schema, from_table, from_column,
                                     to_schema, to_table, to_column)
                    )
                """)
                await cursor.execute("""
                    DELETE FROM datapilot_catalog.relationship_publications
                    WHERE data_source_id=%s AND from_schema=%s AND from_table=%s
                      AND from_column=%s AND to_schema=%s AND to_table=%s AND to_column=%s
                """, (data_source_id, *(review[k] for k in keys)))
                await cursor.execute("""
                    INSERT INTO datapilot_catalog.relationship_verifications
                    (data_source_id, from_schema, from_table, from_column, to_schema,
                     to_table, to_column, review_fingerprint, evidence, verified_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,NOW())
                    ON CONFLICT (data_source_id, from_schema, from_table, from_column,
                                 to_schema, to_table, to_column)
                    DO UPDATE SET review_fingerprint=EXCLUDED.review_fingerprint,
                                  evidence=EXCLUDED.evidence, verified_at=NOW()
                """, (data_source_id, *(review[k] for k in keys),
                      fingerprint, __import__("json").dumps(evidence)))
                return True

    async def get_relationship_verification(
        self, data_source_id: int, review: dict
    ) -> dict | None:
        """Return only evidence bound to the current reviewed contract."""
        from datapilot.application.relationship_evidence import verification_matches_review
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("""
                    SELECT review_fingerprint, evidence, verified_at
                    FROM datapilot_catalog.relationship_verifications
                    WHERE data_source_id=%s AND from_schema=%s AND from_table=%s
                      AND from_column=%s AND to_schema=%s AND to_table=%s AND to_column=%s
                """, (data_source_id, review["from_schema"], review["from_table"],
                      review["from_column"], review["to_schema"], review["to_table"],
                      review["to_column"]))
                row = await cursor.fetchone()
                if row is None:
                    return None
                record = {**row[1], "review_fingerprint": row[0],
                          "verified_at": row[2].isoformat()}
                return record if verification_matches_review(review, record) else None

    async def publish_reviewed_relationship(self, data_source_id: int, review: dict) -> bool:
        """Atomically publish only a fresh, unchanged verified review.

        This persists publication intent; it does NOT activate query joins.
        SQL consumers must independently enforce the approved physical join.
        """
        from datapilot.application.relationship_evidence import review_fingerprint
        from datapilot.application.relationship_freshness import assess_verification_freshness
        from datapilot.application.relationship_publication import assess_relationship_publication
        import json

        await self.list_reviewed_relationships(data_source_id)
        pool = await self._get_pool()
        keys = ("from_schema", "from_table", "from_column",
                "to_schema", "to_table", "to_column")
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("""
                    CREATE TABLE IF NOT EXISTS datapilot_catalog.relationship_publications (
                        data_source_id BIGINT NOT NULL REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE,
                        from_schema TEXT NOT NULL, from_table TEXT NOT NULL, from_column TEXT NOT NULL,
                        to_schema TEXT NOT NULL, to_table TEXT NOT NULL, to_column TEXT NOT NULL,
                        review_fingerprint TEXT NOT NULL,
                        verification_fingerprint TEXT NOT NULL,
                        published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (data_source_id, from_schema, from_table, from_column,
                                     to_schema, to_table, to_column)
                    )
                """)
                await cursor.execute("""
                    SELECT cardinality, review_status, join_policy
                    FROM datapilot_catalog.reviewed_relationships
                    WHERE data_source_id=%s AND from_schema=%s AND from_table=%s
                      AND from_column=%s AND to_schema=%s AND to_table=%s AND to_column=%s
                    FOR UPDATE
                """, (data_source_id, *(review[k] for k in keys)))
                row = await cursor.fetchone()
                if row is None:
                    return False
                persisted = {**{k: review[k] for k in keys},
                             "cardinality": row[0], "review_status": row[1], "join_policy": row[2]}
                fingerprint = review_fingerprint(persisted)
                if fingerprint != review_fingerprint(review):
                    return False
                await cursor.execute("""
                    SELECT review_fingerprint, evidence, verified_at
                    FROM datapilot_catalog.relationship_verifications
                    WHERE data_source_id=%s AND from_schema=%s AND from_table=%s
                      AND from_column=%s AND to_schema=%s AND to_table=%s AND to_column=%s
                    FOR UPDATE
                """, (data_source_id, *(review[k] for k in keys)))
                verified = await cursor.fetchone()
                if verified is None:
                    return False
                evidence = {**verified[1], "review_fingerprint": verified[0],
                            "verified_at": verified[2].isoformat()}
                if not assess_verification_freshness(persisted, evidence).current:
                    return False
                eligible = assess_relationship_publication(
                    persisted,
                    structural_valid=evidence.get("structurally_valid") is True,
                    live_cardinality_verified=evidence.get("live_cardinality_verified") is True,
                    cardinality_holds=evidence.get("cardinality_holds") is True,
                    referential_integrity_checked=evidence.get("referential_integrity_checked") is True,
                    unmatched_references=evidence.get("unmatched_references"),
                    nullable_references=evidence.get("nullable_references"),
                    policy_enforced_by_sql_governance=True,
                )
                if not eligible.eligible:
                    return False
                await cursor.execute("""
                    INSERT INTO datapilot_catalog.relationship_publications
                    (data_source_id, from_schema, from_table, from_column, to_schema,
                     to_table, to_column, review_fingerprint, verification_fingerprint)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (data_source_id, from_schema, from_table, from_column,
                                 to_schema, to_table, to_column)
                    DO UPDATE SET review_fingerprint=EXCLUDED.review_fingerprint,
                                  verification_fingerprint=EXCLUDED.verification_fingerprint,
                                  published_at=NOW()
                """, (data_source_id, *(review[k] for k in keys), fingerprint, verified[0]))
                return True

    async def list_current_relationship_publications(self, data_source_id: int) -> list[dict]:
        """Return only unexpired grants matching the current review and evidence.

        Never accept publication state or freshness from a request payload.
        These grants remain metadata-only until the SQL pipeline is wired.
        """
        from datapilot.application.relationship_evidence import review_fingerprint
        from datapilot.application.relationship_freshness import assess_verification_freshness
        from datapilot.application.relationship_publication import assess_relationship_publication
        await self.list_reviewed_relationships(data_source_id)
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("""
                    SELECT r.from_schema, r.from_table, r.from_column,
                           r.to_schema, r.to_table, r.to_column,
                           r.cardinality, r.review_status, r.join_policy,
                           v.review_fingerprint, v.evidence, v.verified_at,
                           p.review_fingerprint, p.verification_fingerprint,
                           p.published_at
                    FROM datapilot_catalog.relationship_publications p
                    JOIN datapilot_catalog.reviewed_relationships r
                      ON r.data_source_id=p.data_source_id
                     AND r.from_schema=p.from_schema AND r.from_table=p.from_table
                     AND r.from_column=p.from_column AND r.to_schema=p.to_schema
                     AND r.to_table=p.to_table AND r.to_column=p.to_column
                    JOIN datapilot_catalog.relationship_verifications v
                      ON v.data_source_id=r.data_source_id
                     AND v.from_schema=r.from_schema AND v.from_table=r.from_table
                     AND v.from_column=r.from_column AND v.to_schema=r.to_schema
                     AND v.to_table=r.to_table AND v.to_column=r.to_column
                    WHERE p.data_source_id=%s
                """, (data_source_id,))
                rows = await cursor.fetchall()
        grants = []
        keys = ("from_schema", "from_table", "from_column",
                "to_schema", "to_table", "to_column",
                "cardinality", "review_status", "join_policy")
        for row in rows:
            review = dict(zip(keys, row[:9]))
            try:
                fingerprint = review_fingerprint(review)
            except ValueError:
                continue
            if fingerprint != row[9] or fingerprint != row[12] or row[13] != row[9]:
                continue
            evidence = {**row[10], "review_fingerprint": row[9],
                        "verified_at": row[11].isoformat()}
            if not assess_verification_freshness(review, evidence).current:
                continue
            eligible = assess_relationship_publication(
                review,
                structural_valid=evidence.get("structurally_valid") is True,
                live_cardinality_verified=evidence.get("live_cardinality_verified") is True,
                cardinality_holds=evidence.get("cardinality_holds") is True,
                referential_integrity_checked=evidence.get("referential_integrity_checked") is True,
                unmatched_references=evidence.get("unmatched_references"),
                nullable_references=evidence.get("nullable_references"),
                policy_enforced_by_sql_governance=True,
            )
            if eligible.eligible:
                grants.append({**review, "published_at": row[14].isoformat(),
                               "verified_at": row[11].isoformat()})
        return grants

    async def list_catalog_foreign_keys(self, data_source_id: int) -> list[dict]:
        """Return declared constraints from the latest discovered snapshots only."""
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
                    SELECT t.schema_name, t.table_name, fk.constrained_column,
                           fk.referenced_table, fk.referenced_column
                    FROM datapilot_catalog.foreign_keys fk
                    JOIN datapilot_catalog.tables t ON t.id = fk.table_id
                    JOIN latest l ON l.id = t.snapshot_id
                    ORDER BY t.schema_name, t.table_name, fk.constrained_column
                    """,
                    (data_source_id,),
                )
                return [
                    {"schema_name": row[0], "table_name": row[1],
                     "from_column": row[2], "referenced_table": row[3],
                     "to_column": row[4]}
                    for row in await cursor.fetchall()
                ]

    async def get_selected_datasets(self, data_source_id: int) -> list[dict]:
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """CREATE TABLE IF NOT EXISTS datapilot_catalog.selected_datasets (
                        data_source_id BIGINT NOT NULL REFERENCES datapilot_catalog.data_sources(id) ON DELETE CASCADE,
                        schema_name TEXT NOT NULL,
                        table_name TEXT NOT NULL,
                        PRIMARY KEY (data_source_id, schema_name, table_name)
                    )"""
                )
                await cursor.execute(
                    "SELECT schema_name, table_name FROM datapilot_catalog.selected_datasets WHERE data_source_id = %s ORDER BY schema_name, table_name",
                    (data_source_id,),
                )
                return [{"schema_name": row[0], "table_name": row[1]} for row in await cursor.fetchall()]

    async def replace_selected_datasets(self, data_source_id: int, selections: list[dict]) -> None:
        """Atomically replace approved datasets after checking the discovered catalog."""
        discovered = await self.list_catalog_tables(data_source_id)
        allowed = {(row["schema_name"], row["table_name"]) for row in discovered}
        selected = {(row["schema_name"], row["table_name"]) for row in selections}
        if not selected or not selected.issubset(allowed):
            raise ValueError("Selection must contain only discovered datasets and cannot be empty")
        await self.get_selected_datasets(data_source_id)
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute("DELETE FROM datapilot_catalog.selected_datasets WHERE data_source_id = %s", (data_source_id,))
                    for schema_name, table_name in sorted(selected):
                        await cursor.execute(
                            "INSERT INTO datapilot_catalog.selected_datasets (data_source_id, schema_name, table_name) VALUES (%s, %s, %s)",
                            (data_source_id, schema_name, table_name),
                        )

    async def save_semantic_dataset(
        self, *, data_source_id: int, schema_name: str, table_name: str,
        description: Optional[str], business_meaning: Optional[str],
        grain: Optional[str], identity_semantics: Optional[str],
        aliases: list[str], use_cases: list[str], query_constraints: list[str],
    ) -> int:
        """Persist business semantics for one discovered physical dataset."""
        await self.initialize()
        catalog_tables = await self.list_catalog_tables(data_source_id)
        if not any(
            t["schema_name"] == schema_name and t["table_name"] == table_name
            for t in catalog_tables
        ):
            raise MetadataError(
                "Semantic dataset must reference a discovered physical table or view",
                details={"schema_name": schema_name, "table_name": table_name},
            )

        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO datapilot_catalog.semantic_datasets
                            (data_source_id, schema_name, table_name, description,
                             business_meaning, grain, identity_semantics,
                             use_cases, query_constraints)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                        ON CONFLICT (data_source_id, schema_name, table_name) DO UPDATE SET
                            description = EXCLUDED.description,
                            business_meaning = EXCLUDED.business_meaning,
                            grain = EXCLUDED.grain,
                            identity_semantics = EXCLUDED.identity_semantics,
                            use_cases = EXCLUDED.use_cases,
                            query_constraints = EXCLUDED.query_constraints,
                            updated_at = NOW()
                        RETURNING id
                        """,
                        (
                            data_source_id, schema_name, table_name, description,
                            business_meaning, grain, identity_semantics,
                            json.dumps([v.strip() for v in use_cases if v.strip()]),
                            json.dumps([v.strip() for v in query_constraints if v.strip()]),
                        ),
                    )
                    dataset_id = (await cursor.fetchone())[0]
                    await cursor.execute(
                        "DELETE FROM datapilot_catalog.semantic_dataset_aliases WHERE dataset_id = %s",
                        (dataset_id,),
                    )
                    for alias in sorted({a.strip() for a in aliases if a.strip()}):
                        await cursor.execute(
                            """
                            INSERT INTO datapilot_catalog.semantic_dataset_aliases (dataset_id, alias)
                            VALUES (%s, %s)
                            """,
                            (dataset_id, alias),
                        )
                    return dataset_id

    async def list_semantic_datasets(self, data_source_id: int) -> list[dict]:
        """Return configured dataset-level semantics for a data source."""
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT d.id, d.schema_name, d.table_name, d.description,
                           d.business_meaning, d.grain, d.identity_semantics,
                           d.use_cases, d.query_constraints,
                           COALESCE(
                               (SELECT jsonb_agg(a.alias ORDER BY a.alias)
                                FROM datapilot_catalog.semantic_dataset_aliases a
                                WHERE a.dataset_id = d.id),
                               '[]'::jsonb
                           )
                    FROM datapilot_catalog.semantic_datasets d
                    WHERE d.data_source_id = %s
                    ORDER BY d.schema_name, d.table_name
                    """,
                    (data_source_id,),
                )
                return [
                    {
                        "id": row[0], "schema_name": row[1], "table_name": row[2],
                        "description": row[3], "business_meaning": row[4],
                        "grain": row[5], "identity_semantics": row[6],
                        "use_cases": row[7] or [], "query_constraints": row[8] or [],
                        "aliases": row[9] or [],
                    }
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
                        value_mappings = attribute.get("value_mappings") or []
                        canonical_seen = set()
                        synonym_seen = {}
                        for mapping in value_mappings:
                            canonical = mapping["canonical_value"].strip()
                            normalized = canonical.casefold()
                            if not canonical or normalized in canonical_seen:
                                raise MetadataError("Duplicate or empty canonical attribute value")
                            canonical_seen.add(normalized)
                            aliases = sorted({
                                v.strip() for v in mapping.get("synonyms", [])
                                if isinstance(v, str) and v.strip()
                            })
                            # Repeating the canonical value as its own synonym
                            # is harmless (e.g. ON ORDER / on order). Reject only
                            # aliases shared by different canonical values.
                            for alias in [canonical, *aliases]:
                                key = alias.casefold()
                                owner = synonym_seen.get(key)
                                if owner is not None and owner != normalized:
                                    raise MetadataError("Conflicting canonical value synonyms")
                                synonym_seen[key] = normalized
                            await cursor.execute(
                                """
                                INSERT INTO datapilot_catalog.semantic_attribute_values
                                    (attribute_id, canonical_value, synonyms)
                                VALUES (%s, %s, %s::jsonb)
                                """,
                                (attribute_id, canonical, json.dumps(aliases)),
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
                        synonyms = [s[0] for s in await cursor.fetchall()]
                        await cursor.execute(
                            """
                            SELECT canonical_value, synonyms
                            FROM datapilot_catalog.semantic_attribute_values
                            WHERE attribute_id = %s
                            ORDER BY canonical_value
                            """, (attribute[0],),
                        )
                        value_mappings = [
                            {"canonical_value": value, "synonyms": aliases or []}
                            for value, aliases in await cursor.fetchall()
                        ]
                        attributes.append({
                            "name": attribute[1],
                            "description": attribute[2],
                            "column_name": attribute[3],
                            "operators": attribute[4] or ["="],
                            "synonyms": synonyms,
                            "value_mappings": value_mappings,
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


    async def publish_categorical_mappings(
        self, *, data_source_id: int, schema_name: str, table_name: str,
        column_name: str, mappings: list[dict], create_missing_attribute: bool = False,
    ) -> int:
        """Merge mappings; optionally create an approved attribute on an existing entity."""
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """SELECT a.id FROM datapilot_catalog.semantic_attributes a
                           JOIN datapilot_catalog.semantic_entities e ON e.id = a.entity_id
                           WHERE e.data_source_id = %s AND e.schema_name = %s
                             AND e.table_name = %s AND a.column_name = %s
                           FOR UPDATE OF a""",
                        (data_source_id, schema_name, table_name, column_name),
                    )
                    rows = await cursor.fetchall()
                    if len(rows) > 1:
                        raise MetadataError("Ambiguous semantic attribute for publication")
                    if not rows:
                        if not create_missing_attribute:
                            raise MetadataError("Approve attribute creation before publishing")
                        await cursor.execute(
                            """SELECT id FROM datapilot_catalog.semantic_entities
                               WHERE data_source_id = %s AND schema_name = %s AND table_name = %s
                               FOR UPDATE""",
                            (data_source_id, schema_name, table_name),
                        )
                        entities = await cursor.fetchall()
                        if len(entities) != 1:
                            raise MetadataError("Configure a semantic entity for this dataset first")
                        entity_id = entities[0][0]
                        await cursor.execute(
                            """SELECT id FROM datapilot_catalog.semantic_attributes
                               WHERE entity_id = %s AND name = %s FOR UPDATE""",
                            (entity_id, column_name),
                        )
                        if await cursor.fetchone():
                            raise MetadataError("Attribute name already used by another column")
                        await cursor.execute(
                            """INSERT INTO datapilot_catalog.semantic_attributes
                               (entity_id, name, description, column_name, operators)
                               VALUES (%s, %s, %s, %s, '["="]'::jsonb) RETURNING id""",
                            (entity_id, column_name, "Discovered categorical attribute", column_name),
                        )
                        rows = [await cursor.fetchone()]
                    attribute_id = rows[0][0]
                    await cursor.execute(
                        """SELECT canonical_value, synonyms FROM datapilot_catalog.semantic_attribute_values
                           WHERE attribute_id = %s FOR UPDATE""", (attribute_id,),
                    )
                    existing = {value: list(aliases or []) for value, aliases in await cursor.fetchall()}
                    merged = dict(existing)
                    for item in mappings:
                        canonical = item["canonical_value"].strip()
                        if not canonical:
                            raise MetadataError("Canonical value cannot be empty")
                        match = next((v for v in merged if v.casefold() == canonical.casefold()), canonical)
                        aliases = merged.get(match, []) + list(item.get("synonyms") or [])
                        merged[match] = sorted({v.strip() for v in aliases if isinstance(v, str) and v.strip() and v.strip().casefold() != match.casefold()})
                    ownership = {}
                    for canonical, aliases in merged.items():
                        for term in [canonical, *aliases]:
                            key = term.casefold()
                            if key in ownership and ownership[key] != canonical.casefold():
                                raise MetadataError("Conflicting canonical value synonyms")
                            ownership[key] = canonical.casefold()
                    for canonical, aliases in merged.items():
                        await cursor.execute(
                            """INSERT INTO datapilot_catalog.semantic_attribute_values
                               (attribute_id, canonical_value, synonyms)
                               VALUES (%s, %s, %s::jsonb)
                               ON CONFLICT (attribute_id, canonical_value)
                               DO UPDATE SET synonyms = EXCLUDED.synonyms""",
                            (attribute_id, canonical, json.dumps(aliases)),
                        )
                    return len(mappings)

    async def save_time_dimension(
        self, *, data_source_id: int, entity_id: int, name: str,
        column_name: str, role: str, grain: str, timezone: str,
        is_default: bool, synonyms: list[str],
    ) -> int:
        """Persist a governed date/time role on a semantic entity."""
        await self.initialize()
        allowed_grains = {"date", "day", "week", "month", "quarter", "year", "timestamp"}
        if grain not in allowed_grains:
            raise MetadataError("Unsupported time-dimension grain")
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT e.schema_name, e.table_name
                        FROM datapilot_catalog.semantic_entities e
                        WHERE e.data_source_id = %s AND e.id = %s
                        """,
                        (data_source_id, entity_id),
                    )
                    entity = await cursor.fetchone()
                    if not entity:
                        raise MetadataError("Time dimension entity must belong to the selected data source")
                    await cursor.execute(
                        """
                        SELECT COUNT(*)
                        FROM datapilot_catalog.semantic_attributes a
                        WHERE a.entity_id = %s AND a.column_name = %s
                        """,
                        (entity_id, column_name),
                    )
                    if (await cursor.fetchone())[0] == 0:
                        raise MetadataError(
                            "Time dimension column must be exposed as a semantic attribute",
                            details={"column_name": column_name},
                        )
                    if is_default:
                        await cursor.execute(
                            """
                            UPDATE datapilot_catalog.semantic_time_dimensions
                            SET is_default = FALSE, updated_at = NOW()
                            WHERE data_source_id = %s AND entity_id = %s
                            """,
                            (data_source_id, entity_id),
                        )
                    await cursor.execute(
                        """
                        INSERT INTO datapilot_catalog.semantic_time_dimensions
                            (data_source_id, entity_id, name, column_name, role, grain,
                             timezone, is_default, synonyms)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        ON CONFLICT (data_source_id, name) DO UPDATE SET
                            entity_id = EXCLUDED.entity_id,
                            column_name = EXCLUDED.column_name,
                            role = EXCLUDED.role,
                            grain = EXCLUDED.grain,
                            timezone = EXCLUDED.timezone,
                            is_default = EXCLUDED.is_default,
                            synonyms = EXCLUDED.synonyms,
                            updated_at = NOW()
                        RETURNING id
                        """,
                        (
                            data_source_id, entity_id, name, column_name, role, grain,
                            timezone, is_default,
                            json.dumps(sorted({s.strip() for s in synonyms if s.strip()})),
                        ),
                    )
                    return (await cursor.fetchone())[0]

    async def list_time_dimensions(self, data_source_id: int) -> list[dict]:
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT td.id, td.name, td.entity_id, e.name, e.schema_name, e.table_name,
                           td.column_name, td.role, td.grain, td.timezone, td.is_default,
                           td.synonyms
                    FROM datapilot_catalog.semantic_time_dimensions td
                    JOIN datapilot_catalog.semantic_entities e ON e.id = td.entity_id
                    WHERE td.data_source_id = %s
                    ORDER BY e.name, td.is_default DESC, td.name
                    """,
                    (data_source_id,),
                )
                return [{
                    "id": row[0], "name": row[1], "entity_id": row[2],
                    "entity_name": row[3], "schema_name": row[4], "table_name": row[5],
                    "column_name": row[6], "role": row[7], "grain": row[8],
                    "timezone": row[9], "is_default": row[10],
                    "synonyms": row[11] or [],
                } for row in await cursor.fetchall()]

    async def save_semantic_relationship(
        self, *, data_source_id: int, name: str, from_entity_id: int,
        from_column: str, to_entity_id: int, to_column: str,
        cardinality: str, description: Optional[str],
        join_policy: str = "unconfigured",
    ) -> int:
        await self.initialize()
        if join_policy not in {"unconfigured", "preserve_source", "matched_only"}:
            raise MetadataError("Unsupported semantic relationship join policy")
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
                             to_entity_id, to_column, cardinality, description, join_policy)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (data_source_id, name) DO UPDATE SET
                            from_entity_id = EXCLUDED.from_entity_id,
                            from_column = EXCLUDED.from_column,
                            to_entity_id = EXCLUDED.to_entity_id,
                            to_column = EXCLUDED.to_column,
                            cardinality = EXCLUDED.cardinality,
                            description = EXCLUDED.description,
                            join_policy = EXCLUDED.join_policy,
                            updated_at = NOW()
                        RETURNING id
                        """,
                        (data_source_id, name, from_entity_id, from_column,
                         to_entity_id, to_column, cardinality, description, join_policy),
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
                           r.description, r.join_policy
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
                    "description": row[9], "join_policy": row[10],
                } for row in await cursor.fetchall()]

    async def save_semantic_metric(
        self, *, data_source_id: int, name: str, description: Optional[str],
        entity_id: int, attribute_name: Optional[str], aggregation: str,
        format: str, synonyms: list[str], calculation_expression: Optional[str] = None,
    ) -> int:
        await self.initialize()
        allowed = {"sum", "count", "count_distinct", "avg", "min", "max"}
        if aggregation not in allowed:
            raise MetadataError("Unsupported metric aggregation")
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    expression = (calculation_expression or "").strip() or None
                    if expression is None:
                        if not attribute_name:
                            raise MetadataError("Simple metric requires an attribute")
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
                    else:
                        # Derived expressions are deliberately limited to columns on the
                        # metric's base entity. SQL safety is validated before persistence.
                        await cursor.execute(
                            """
                            SELECT a.column_name
                            FROM datapilot_catalog.semantic_attributes a
                            JOIN datapilot_catalog.semantic_entities e ON e.id = a.entity_id
                            WHERE e.data_source_id = %s AND e.id = %s
                            """,
                            (data_source_id, entity_id),
                        )
                        allowed_columns = {row[0].lower() for row in await cursor.fetchall()}
                        try:
                            from sqlglot import parse_one, exp
                            tree = parse_one(expression, read="postgres")
                        except Exception as exc:
                            raise MetadataError(
                                "Derived metric calculation expression is not valid SQL",
                                details={"error_type": type(exc).__name__},
                            ) from exc
                        if any(tree.find(kind) is not None for kind in (exp.Select, exp.Subquery, exp.Insert, exp.Update, exp.Delete)):
                            raise MetadataError("Derived metric expression must be a row-level scalar expression")
                        referenced = {column.name.lower() for column in tree.find_all(exp.Column)}
                        unknown = sorted(referenced - allowed_columns)
                        if unknown:
                            raise MetadataError(
                                "Derived metric expression references columns outside the selected entity",
                                details={"unknown_columns": unknown},
                            )
                    await cursor.execute(
                        """
                        INSERT INTO datapilot_catalog.semantic_metrics
                            (data_source_id, name, description, entity_id,
                             attribute_name, aggregation, format, calculation_expression)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (data_source_id, name) DO UPDATE SET
                            description = EXCLUDED.description,
                            entity_id = EXCLUDED.entity_id,
                            attribute_name = EXCLUDED.attribute_name,
                            aggregation = EXCLUDED.aggregation,
                            format = EXCLUDED.format,
                            calculation_expression = EXCLUDED.calculation_expression,
                            updated_at = NOW()
                        RETURNING id
                        """,
                        (data_source_id, name, description, entity_id,
                         attribute_name, aggregation, format, expression),
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

    async def save_semantic_ranking_rule(
        self, *, data_source_id: int, entity_id: int, name: str,
        dimension_attribute_name: str, metric_id: int, default_top_n: int = 10,
        direction: str = "desc", scope: str = "global", is_default: bool = False,
    ) -> int:
        """Store an approved ranking rule; never infer a metric from physical columns."""
        await self.initialize()
        if not 1 <= default_top_n <= 100 or direction not in {"asc", "desc"} or scope not in {"global", "per_group"}:
            raise MetadataError("Invalid ranking rule configuration")
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT 1 FROM datapilot_catalog.semantic_entities e
                        JOIN datapilot_catalog.semantic_attributes a ON a.entity_id = e.id
                        JOIN datapilot_catalog.semantic_metrics m ON m.entity_id = e.id
                        WHERE e.data_source_id = %s AND e.id = %s
                          AND a.name = %s AND m.id = %s AND m.data_source_id = %s
                        """,
                        (data_source_id, entity_id, dimension_attribute_name, metric_id, data_source_id),
                    )
                    if await cursor.fetchone() is None:
                        raise MetadataError("Ranking dimension and metric must belong to the selected entity")
                    if is_default:
                        await cursor.execute(
                            """UPDATE datapilot_catalog.semantic_ranking_rules
                               SET is_default = FALSE, updated_at = NOW()
                               WHERE data_source_id = %s AND entity_id = %s""",
                            (data_source_id, entity_id),
                        )
                    await cursor.execute(
                        """
                        INSERT INTO datapilot_catalog.semantic_ranking_rules
                            (data_source_id, entity_id, name, dimension_attribute_name,
                             metric_id, default_top_n, direction, scope, is_default)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (data_source_id, entity_id, name) DO UPDATE SET
                            dimension_attribute_name = EXCLUDED.dimension_attribute_name,
                            metric_id = EXCLUDED.metric_id,
                            default_top_n = EXCLUDED.default_top_n,
                            direction = EXCLUDED.direction,
                            scope = EXCLUDED.scope,
                            is_default = EXCLUDED.is_default,
                            updated_at = NOW()
                        RETURNING id
                        """,
                        (data_source_id, entity_id, name, dimension_attribute_name,
                         metric_id, default_top_n, direction, scope, is_default),
                    )
                    return (await cursor.fetchone())[0]

    async def list_semantic_ranking_rules(self, data_source_id: int) -> list[dict]:
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT r.id, r.name, r.entity_id, e.name, r.dimension_attribute_name,
                           r.metric_id, m.name, r.default_top_n, r.direction, r.scope, r.is_default
                    FROM datapilot_catalog.semantic_ranking_rules r
                    JOIN datapilot_catalog.semantic_entities e ON e.id = r.entity_id
                    JOIN datapilot_catalog.semantic_metrics m ON m.id = r.metric_id
                    WHERE r.data_source_id = %s
                    ORDER BY e.name, r.name
                    """,
                    (data_source_id,),
                )
                return [{
                    "id": row[0], "name": row[1], "entity_id": row[2],
                    "entity_name": row[3], "dimension_attribute_name": row[4],
                    "metric_id": row[5], "metric_name": row[6],
                    "default_top_n": row[7], "direction": row[8],
                    "scope": row[9], "is_default": row[10],
                } for row in await cursor.fetchall()]

    async def list_semantic_metrics(self, data_source_id: int) -> list[dict]:
        await self.initialize()
        pool = await self._get_pool()
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT m.id, m.name, m.description, m.entity_id, e.name,
                           m.attribute_name, m.aggregation, m.format, m.calculation_expression,
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
                    "format": row[7], "calculation_expression": row[8],
                    "metric_type": "derived" if row[8] else "simple",
                    "synonyms": row[9] or [],
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
                                "DELETE FROM datapilot_catalog.discovered_unique_constraints WHERE table_id = %s", (table_id,)
                            )
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

                            for unique in table.unique_constraints:
                                await cursor.execute(
                                    """
                                    INSERT INTO datapilot_catalog.discovered_unique_constraints
                                        (table_id, constraint_name, columns, is_primary_key)
                                    VALUES (%s, %s, %s::jsonb, %s)
                                    """,
                                    (table_id, unique.name, json.dumps(unique.columns), unique.is_primary_key),
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
