"""PostgreSQL persistence for query history and diagnostic lineage."""

from __future__ import annotations

from typing import Any, Optional

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from datapilot.core.exceptions import DatabaseConnectionError
from datapilot.domain.query import QueryRequest, QueryResponse


class PostgreSQLQueryHistoryStore:
    """Persist completed query attempts in the Data Pilot metadata database."""

    def __init__(self, database_url: str, pool_size: int = 3) -> None:
        if not database_url:
            raise DatabaseConnectionError("Metadata PostgreSQL database URL is required")
        self._database_url = database_url
        self._pool_size = pool_size
        self._pool: Optional[AsyncConnectionPool] = None

    async def initialize(self) -> None:
        if self._pool is None:
            self._pool = AsyncConnectionPool(
                conninfo=self._database_url,
                min_size=1,
                max_size=self._pool_size,
                open=False,
            )
            await self._pool.open()
        async with self._pool.connection() as conn:
            await conn.execute("CREATE SCHEMA IF NOT EXISTS datapilot_catalog")
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS datapilot_catalog.query_history (
                    id BIGSERIAL PRIMARY KEY,
                    source_name TEXT,
                    question TEXT NOT NULL,
                    status TEXT NOT NULL,
                    dry_run BOOLEAN NOT NULL DEFAULT FALSE,
                    sql TEXT,
                    governed_datasets JSONB NOT NULL DEFAULT '[]'::jsonb,
                    governed_entities JSONB NOT NULL DEFAULT '[]'::jsonb,
                    governed_metrics JSONB NOT NULL DEFAULT '[]'::jsonb,
                    row_count INTEGER,
                    execution_time_ms DOUBLE PRECISION,
                    response JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_datapilot_query_history_source_created
                ON datapilot_catalog.query_history (source_name, created_at DESC)
                """
            )
            await conn.commit()

    async def record(self, request: QueryRequest, response: QueryResponse) -> int:
        await self.initialize()
        assert self._pool is not None
        trace = response.trace
        result = response.result
        row_count = getattr(result, "row_count", None) if result is not None else None
        execution_time_ms = getattr(result, "execution_time_ms", None) if result is not None else None
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO datapilot_catalog.query_history (
                    source_name, question, status, dry_run, sql,
                    governed_datasets, governed_entities, governed_metrics,
                    row_count, execution_time_ms, response
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    request.source_name,
                    request.question,
                    response.status,
                    request.dry_run,
                    response.sql,
                    Jsonb(trace.governed_datasets if trace else []),
                    Jsonb(trace.governed_entities if trace else []),
                    Jsonb(trace.governed_metrics if trace else []),
                    row_count,
                    execution_time_ms,
                    Jsonb(response.model_dump(mode="json")),
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("Query history INSERT did not return an id")
            # Metadata connections may use dict_row, so support both mapping and
            # positional row factories rather than assuming tuple-style access.
            history_id = row["id"] if isinstance(row, dict) else row[0]
            await conn.commit()
            return int(history_id)

    async def list(self, *, source_name: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        await self.initialize()
        assert self._pool is not None
        limit = max(1, min(limit, 200))
        where = "WHERE source_name = %s" if source_name else ""
        params: tuple[Any, ...] = (source_name, limit) if source_name else (limit,)
        async with self._pool.connection() as conn:
            conn.row_factory = dict_row
            cursor = await conn.execute(
                f"""
                SELECT id, source_name, question, status, dry_run, sql,
                       governed_datasets, governed_entities, governed_metrics,
                       row_count, execution_time_ms, created_at
                FROM datapilot_catalog.query_history
                {where}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                params,
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def get(self, history_id: int) -> Optional[dict[str, Any]]:
        await self.initialize()
        assert self._pool is not None
        async with self._pool.connection() as conn:
            conn.row_factory = dict_row
            cursor = await conn.execute(
                """
                SELECT id, source_name, question, status, dry_run, sql,
                       governed_datasets, governed_entities, governed_metrics,
                       row_count, execution_time_ms, response, created_at
                FROM datapilot_catalog.query_history
                WHERE id = %s
                """,
                (history_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
