"""Optional integration tests for a real PostgreSQL database."""

import os

import pytest

from datapilot.infrastructure.database.postgresql import PostgreSQLDatabaseProvider

POSTGRES_URL = os.getenv("DATAPILOT_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="Set DATAPILOT_TEST_POSTGRES_URL to run PostgreSQL integration tests",
)


@pytest.mark.asyncio
async def test_ping_and_execute() -> None:
    provider = PostgreSQLDatabaseProvider(POSTGRES_URL or "")
    try:
        assert await provider.ping() is True
        result = await provider.execute_query("SELECT 1 AS value")
        assert result.columns == ["value"]
        assert result.rows == [[1]]
        assert result.row_count == 1
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_introspect_schema() -> None:
    provider = PostgreSQLDatabaseProvider(POSTGRES_URL or "")
    try:
        schema = await provider.introspect_schema("public")
        assert schema.dialect == "postgresql"
        assert isinstance(schema.tables, list)
    finally:
        await provider.close()
