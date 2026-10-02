"""PostgreSQL persistence adapter for the semantic catalog."""

from __future__ import annotations

import hashlib
import json
from typing import Optional

from psycopg.rows import tuple_row
from psycopg_pool import AsyncConnectionPool

from datapilot.core.exceptions import DatabaseConnectionError, MetadataError
from datapilot.domain.semantic import SemanticCatalog


class PostgreSQLSemanticCatalogProvider:
    """Store the editable semantic catalog as versioned JSONB in PostgreSQL."""

    def __init__(self, database_url: str, pool_size: int = 2) -> None:
        if not database_url:
            raise DatabaseConnectionError("Semantic catalog database URL is required")
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
        except Exception as exc:
            await pool.close()
            raise DatabaseConnectionError(
                "Unable to connect to semantic catalog PostgreSQL database",
                details={"error_type": type(exc).__name__},
            ) from exc
        self._pool = pool
        return pool

    async def initialize(self) -> None:
        pool = await self._get_pool()
        try:
            async with pool.connection() as connection:
                async with connection.transaction():
                    async with connection.cursor() as cursor:
                        await cursor.execute(
                            """
                            CREATE SCHEMA IF NOT EXISTS datapilot_catalog;
                            CREATE TABLE IF NOT EXISTS datapilot_catalog.semantic_catalog (
                                id SMALLINT PRIMARY KEY CHECK (id = 1),
                                version TEXT NOT NULL,
                                payload JSONB NOT NULL,
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
        except Exception as exc:
            raise MetadataError(
                "Failed to initialize semantic catalog",
                details={"error_type": type(exc).__name__},
            ) from exc

    @staticmethod
    def _version(catalog: SemanticCatalog) -> str:
        payload = catalog.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    async def get_catalog(self) -> SemanticCatalog:
        pool = await self._get_pool()
        try:
            async with pool.connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        "SELECT payload FROM datapilot_catalog.semantic_catalog WHERE id = 1"
                    )
                    row = await cursor.fetchone()
                    if row is None:
                        return SemanticCatalog()
                    return SemanticCatalog.model_validate(row[0])
        except Exception as exc:
            raise MetadataError(
                "Failed to load semantic catalog",
                details={"error_type": type(exc).__name__},
            ) from exc

    async def save_catalog(self, catalog: SemanticCatalog) -> None:
        payload = catalog.model_dump(mode="json")
        version = self._version(catalog)
        pool = await self._get_pool()
        try:
            async with pool.connection() as connection:
                async with connection.transaction():
                    async with connection.cursor() as cursor:
                        await cursor.execute(
                            """
                            CREATE SCHEMA IF NOT EXISTS datapilot_catalog;
                            CREATE TABLE IF NOT EXISTS datapilot_catalog.semantic_catalog (
                                id SMALLINT PRIMARY KEY CHECK (id = 1),
                                version TEXT NOT NULL,
                                payload JSONB NOT NULL,
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            );
                            INSERT INTO datapilot_catalog.semantic_catalog (id, version, payload)
                            VALUES (1, %s, %s::jsonb)
                            ON CONFLICT (id) DO UPDATE SET
                                version = EXCLUDED.version,
                                payload = EXCLUDED.payload,
                                updated_at = NOW()
                            """,
                            (version, json.dumps(payload)),
                        )
        except Exception as exc:
            raise MetadataError(
                "Failed to persist semantic catalog",
                details={"error_type": type(exc).__name__},
            ) from exc

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
