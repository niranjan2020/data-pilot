"""Unit tests for the PostgreSQL database provider."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from datapilot.core.exceptions import DatabaseExecutionError
from datapilot.domain.interfaces.database import DatabaseProvider
from datapilot.infrastructure.database.postgresql import PostgreSQLDatabaseProvider


def provider() -> PostgreSQLDatabaseProvider:
    return PostgreSQLDatabaseProvider(
        "postgresql://user:password@localhost:5432/db",
        pool_size=5,
        default_timeout_seconds=30.0,
    )


def test_dialect() -> None:
    assert provider().dialect == "postgresql"


def test_protocol_conformance() -> None:
    assert isinstance(provider(), DatabaseProvider)


def test_empty_database_url_is_rejected() -> None:
    with pytest.raises(Exception):
        PostgreSQLDatabaseProvider("")


@pytest.mark.parametrize("keyword", ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE"])
def test_forbidden_statements_are_rejected(keyword: str) -> None:
    with pytest.raises(DatabaseExecutionError):
        provider()._validate_read_only_sql(f"{keyword} something")


def test_select_is_allowed() -> None:
    provider()._validate_read_only_sql("SELECT 1")


def test_with_is_allowed() -> None:
    provider()._validate_read_only_sql("WITH x AS (SELECT 1) SELECT * FROM x")


def test_multiple_statements_are_rejected() -> None:
    with pytest.raises(DatabaseExecutionError):
        provider()._validate_read_only_sql("SELECT 1; SELECT 2")


def test_sql_in_string_literal_does_not_trigger_forbidden_keyword() -> None:
    provider()._validate_read_only_sql("SELECT 'DROP TABLE test'")


@pytest.mark.asyncio
async def test_ping_returns_true_when_connection_succeeds() -> None:
    p = provider()
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=None)
    cursor = MagicMock()
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=None)
    cursor.execute = AsyncMock()
    cursor.fetchone = AsyncMock(return_value=(1,))
    conn.cursor.return_value = cursor
    pool = MagicMock()
    pool.connection.return_value = conn
    p._pool = pool

    assert await p.ping() is True


@pytest.mark.asyncio
async def test_ping_returns_false_when_query_fails() -> None:
    p = provider()
    pool = MagicMock()
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=None)
    cursor = MagicMock()
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=None)
    cursor.execute = AsyncMock(side_effect=RuntimeError("boom"))
    conn.cursor.return_value = cursor
    pool.connection.return_value = conn
    p._pool = pool

    assert await p.ping() is False


@pytest.mark.asyncio
async def test_close_closes_pool() -> None:
    p = provider()
    pool = AsyncMock()
    p._pool = pool

    await p.close()

    pool.close.assert_awaited_once()
    assert p._pool is None
