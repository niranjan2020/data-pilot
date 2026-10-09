"""C4 bounded categorical discovery, without a live database."""

from unittest.mock import AsyncMock

import pytest

from datapilot.infrastructure.database.postgresql import PostgreSQLDatabaseProvider


class Context:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *args):
        return False


def provider_with_rows(rows):
    provider = PostgreSQLDatabaseProvider("postgresql://localhost/test")
    cursor = AsyncMock()
    cursor.fetchall.return_value = rows
    connection = AsyncMock()
    connection.cursor = lambda: Context(cursor)
    connection.transaction = lambda: Context(None)
    pool = AsyncMock()
    pool.connection = lambda: Context(connection)
    provider._get_pool = AsyncMock(return_value=pool)
    return provider, cursor


@pytest.mark.asyncio
async def test_bounded_categorical_values_are_proposals_only():
    provider, cursor = provider_with_rows([("DELIVERED",), ("ON ORDER",)])
    result = await provider.propose_categorical_values("astra", "vessels", "vessel_status", max_values=3)
    assert result == {"status": "proposed", "values": ["DELIVERED", "ON ORDER"], "complete": True}
    assert cursor.execute.await_count == 3
    query, params = cursor.execute.await_args.args
    assert "DISTINCT" in query.as_string(None)
    assert params == (4,)


@pytest.mark.asyncio
async def test_high_cardinality_withholds_partial_suggestions():
    provider, _ = provider_with_rows([("A",), ("B",), ("C",)])
    assert await provider.propose_categorical_values("astra", "vessels", "status", max_values=2) == {
        "status": "high_cardinality", "values": [], "complete": False,
    }


@pytest.mark.asyncio
async def test_invalid_limits_rejected_before_database_access():
    provider, _ = provider_with_rows([])
    with pytest.raises(ValueError):
        await provider.propose_categorical_values("astra", "vessels", "status", max_values=101)
    with pytest.raises(ValueError):
        await provider.propose_categorical_values("astra", "vessels", "status", timeout_seconds=10)
    provider._get_pool.assert_not_awaited()
