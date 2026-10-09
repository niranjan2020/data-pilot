"""Regression for the C4 catalog restore query shape (no live database required)."""

from unittest.mock import AsyncMock

import pytest

from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider


class _Context:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *args):
        return False


@pytest.mark.asyncio
async def test_catalog_tables_includes_columns_and_unique_constraints():
    provider = PostgreSQLMetadataProvider("postgresql://localhost/unused")
    provider.initialize = AsyncMock()
    cursor = AsyncMock()
    cursor.fetchall.return_value = [
        ("astra", "vessels", [{"name": "vessels_pkey", "columns": ["id"], "is_primary_key": True}],
         [{"name": "id", "data_type": "integer", "is_primary_key": True}])
    ]
    connection = AsyncMock()
    connection.cursor = lambda: _Context(cursor)
    pool = AsyncMock()
    pool.connection = lambda: _Context(connection)
    provider._get_pool = AsyncMock(return_value=pool)

    tables = await provider.list_catalog_tables(7)

    assert tables[0]["unique_constraints"][0]["columns"] == ["id"]
    assert tables[0]["columns"][0]["name"] == "id"
    sql, params = cursor.execute.await_args.args
    assert "discovered_unique_constraints" in sql
    assert "AS unique_constraints" in sql
    assert "GROUP BY t.id" in sql
    assert params == (7,)


@pytest.mark.asyncio
async def test_catalog_tables_legacy_empty_constraints():
    provider = PostgreSQLMetadataProvider("postgresql://localhost/unused")
    provider.initialize = AsyncMock()
    cursor = AsyncMock()
    cursor.fetchall.return_value = [("astra", "fixtures", [], [{"name": "id"}])]
    connection = AsyncMock()
    connection.cursor = lambda: _Context(cursor)
    pool = AsyncMock()
    pool.connection = lambda: _Context(connection)
    provider._get_pool = AsyncMock(return_value=pool)

    assert (await provider.list_catalog_tables(7))[0]["unique_constraints"] == []
