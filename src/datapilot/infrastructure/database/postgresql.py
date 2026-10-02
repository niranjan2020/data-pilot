"""PostgreSQL implementation of the Data Pilot DatabaseProvider."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Dict, Optional

from psycopg.rows import tuple_row
from psycopg_pool import AsyncConnectionPool

from datapilot.core.exceptions import DatabaseConnectionError, DatabaseExecutionError
from datapilot.domain.interfaces.database import DatabaseProvider
from datapilot.domain.models import (
    ColumnMetadata,
    ForeignKeyMetadata,
    QueryResult,
    SchemaMetadata,
    TableMetadata,
)

_FORBIDDEN_STATEMENT_RE = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|MERGE|CALL|DO)\b",
    re.IGNORECASE,
)
_COMMENT_OR_LITERAL_RE = re.compile(r"(--[^\n]*|/\*.*?\*/|'(?:''|[^'])*')", re.DOTALL)


class PostgreSQLDatabaseProvider(DatabaseProvider):
    """Async PostgreSQL database adapter backed by psycopg 3 connection pooling."""

    def __init__(
        self,
        database_url: str,
        pool_size: int = 5,
        default_timeout_seconds: float = 30.0,
    ) -> None:
        if not database_url:
            raise DatabaseConnectionError("PostgreSQL database URL is required")
        if pool_size < 1:
            raise ValueError("pool_size must be at least 1")
        if default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be greater than 0")

        self._database_url = database_url
        self._pool_size = pool_size
        self._default_timeout_seconds = default_timeout_seconds
        self._pool: Optional[AsyncConnectionPool] = None
        self._pool_lock = asyncio.Lock()
        self._closed = False

    @property
    def dialect(self) -> str:
        return "postgresql"

    async def _get_pool(self) -> AsyncConnectionPool:
        if self._closed:
            raise DatabaseConnectionError("PostgreSQL provider is closed")
        if self._pool is not None:
            return self._pool

        async with self._pool_lock:
            if self._closed:
                raise DatabaseConnectionError("PostgreSQL provider is closed")
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
                await pool.open(wait=True, timeout=self._default_timeout_seconds)
            except Exception as exc:  # pragma: no cover - exact psycopg exception varies
                await pool.close()
                raise DatabaseConnectionError(
                    "Unable to connect to PostgreSQL",
                    details={"error_type": type(exc).__name__},
                ) from exc
            self._pool = pool
            return pool

    @staticmethod
    def _validate_read_only_sql(sql: str) -> None:
        if not isinstance(sql, str) or not sql.strip():
            raise DatabaseExecutionError("SQL query must be a non-empty string")

        stripped = sql.strip()
        without_comments_literals = _COMMENT_OR_LITERAL_RE.sub(" ", stripped)

        body = without_comments_literals.strip()
        if body.endswith(";"):
            body = body[:-1].rstrip()
        if ";" in body:
            raise DatabaseExecutionError("Multiple SQL statements are not allowed")

        statement = without_comments_literals.lstrip("( ")
        if not re.match(r"^(?:SELECT|WITH|EXPLAIN)\b", statement, re.IGNORECASE):
            raise DatabaseExecutionError("Only read-only SELECT/WITH/EXPLAIN statements are allowed")

        if _FORBIDDEN_STATEMENT_RE.search(without_comments_literals):
            raise DatabaseExecutionError("SQL statement contains a prohibited operation")

    async def ping(self) -> bool:
        try:
            pool = await self._get_pool()
            async with pool.connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute("SELECT 1")
                    await cursor.fetchone()
            return True
        except DatabaseConnectionError:
            raise
        except Exception:
            return False

    async def introspect_schema(self, schema_name: Optional[str] = None) -> SchemaMetadata:
        schema = schema_name or "public"

        table_sql = """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """
        column_sql = """
            SELECT
                c.table_schema,
                c.table_name,
                c.column_name,
                c.data_type,
                c.is_nullable,
                CASE WHEN pk.column_name IS NOT NULL THEN TRUE ELSE FALSE END AS is_primary_key,
                c.ordinal_position
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT kcu.table_schema, kcu.table_name, kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                 AND tc.table_name = kcu.table_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
            ) pk
              ON pk.table_schema = c.table_schema
             AND pk.table_name = c.table_name
             AND pk.column_name = c.column_name
            WHERE c.table_schema = %s
            ORDER BY c.table_name, c.ordinal_position
        """
        fk_sql = """
            SELECT
                tc.table_name AS table_name,
                kcu.column_name AS constrained_column,
                ccu.table_name AS referenced_table,
                ccu.column_name AS referenced_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
             AND tc.table_name = kcu.table_name
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.constraint_schema = tc.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = %s
            ORDER BY tc.table_name, kcu.column_name
        """

        try:
            pool = await self._get_pool()
            async with pool.connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(table_sql, (schema,))
                    table_rows = await cursor.fetchall()

                    await cursor.execute(column_sql, (schema,))
                    column_rows = await cursor.fetchall()

                    await cursor.execute(fk_sql, (schema,))
                    fk_rows = await cursor.fetchall()
        except DatabaseConnectionError:
            raise
        except Exception as exc:
            raise DatabaseExecutionError(
                "Failed to introspect PostgreSQL schema",
                details={"error_type": type(exc).__name__, "schema": schema},
            ) from exc

        tables = {
            row[1]: TableMetadata(name=row[1], schema_name=row[0])
            for row in table_rows
        }

        for row in column_rows:
            table = tables.get(row[1])
            if table is None:
                continue
            column = ColumnMetadata(
                name=row[2],
                data_type=row[3],
                is_nullable=row[4].upper() == "YES" if isinstance(row[4], str) else bool(row[4]),
                is_primary_key=bool(row[5]),
            )
            table.columns.append(column)
            if column.is_primary_key:
                table.primary_keys.append(column.name)

        for row in fk_rows:
            table = tables.get(row[0])
            if table is None:
                continue
            table.foreign_keys.append(
                ForeignKeyMetadata(
                    constrained_column=row[1],
                    referenced_table=row[2],
                    referenced_column=row[3],
                )
            )

        return SchemaMetadata(
            tables=list(tables.values()),
            dialect=self.dialect,
        )

    async def execute_query(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> QueryResult:
        self._validate_read_only_sql(sql)
        timeout = timeout_seconds if timeout_seconds is not None else self._default_timeout_seconds
        if timeout <= 0:
            raise DatabaseExecutionError("timeout_seconds must be greater than 0")

        started = time.perf_counter()
        try:
            pool = await self._get_pool()
            async with pool.connection() as connection:
                await connection.set_read_only(True)
                try:
                    async with connection.transaction():
                        async with connection.cursor() as cursor:
                            await cursor.execute("SET LOCAL statement_timeout = %s", (int(timeout * 1000),))
                            await cursor.execute(sql, params or {})
                            columns = [desc.name for desc in (cursor.description or [])]
                            rows = await cursor.fetchall() if cursor.description else []
                            execution_time_ms = (time.perf_counter() - started) * 1000
                            return QueryResult(
                                columns=columns,
                                rows=[list(row) for row in rows],
                                row_count=len(rows),
                                execution_time_ms=execution_time_ms,
                            )
                finally:
                    await connection.set_read_only(None)
        except DatabaseConnectionError:
            raise
        except Exception as exc:
            raise DatabaseExecutionError(
                "PostgreSQL query execution failed",
                details={"error_type": type(exc).__name__},
            ) from exc

    async def close(self) -> None:
        self._closed = True
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
