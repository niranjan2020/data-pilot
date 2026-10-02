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

CREATE TABLE IF NOT EXISTS datapilot_catalog.schema_snapshots (
    id BIGSERIAL PRIMARY KEY,
    schema_name TEXT NOT NULL,
    dialect TEXT NOT NULL,
    version TEXT NOT NULL,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (schema_name, version)
);

CREATE INDEX IF NOT EXISTS ix_datapilot_schema_snapshots_latest
    ON datapilot_catalog.schema_snapshots (schema_name, discovered_at DESC);

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
                        for statement in _CATALOG_DDL.split(";"):\n                        statement = statement.strip()\n                        if statement:\n                            await cursor.execute(statement)
        except DatabaseConnectionError:
            raise
        except Exception as exc:
            raise MetadataError(
                "Failed to initialize the Data Pilot metadata catalog",
                details={"error_type": type(exc).__name__},
            ) from exc

    @staticmethod
    def _schema_name(schema: SchemaMetadata) -> str:
        if schema.schema_name:
            return schema.schema_name
        names = {table.schema_name for table in schema.tables if table.schema_name}
        if len(names) == 1:
            return next(iter(names))
        return "public"

    async def save_schema(self, schema: SchemaMetadata) -> None:
        if not schema.version:
            raise MetadataError("Schema version is required before persisting metadata")

        pool = await self._get_pool()
        schema_name = self._schema_name(schema)
        try:
            async with pool.connection() as connection:
                async with connection.transaction():
                    async with connection.cursor() as cursor:
                        for statement in _CATALOG_DDL.split(";"):\n                            statement = statement.strip()\n                            if statement:\n                                await cursor.execute(statement)
                        await cursor.execute(
                            """
                            INSERT INTO datapilot_catalog.schema_snapshots (schema_name, dialect, version)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (schema_name, version) DO NOTHING
                            RETURNING id
                            """,
                            (schema_name, schema.dialect, schema.version),
                        )
                        row = await cursor.fetchone()
                        if row is None:
                            await cursor.execute(
                                """
                                SELECT id FROM datapilot_catalog.schema_snapshots
                                WHERE schema_name = %s AND version = %s
                                """,
                                (schema_name, schema.version),
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
