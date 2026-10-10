"""Real PostgreSQL regression cases for governed array and aggregation semantics.

Run with DATAPILOT_TEST_POSTGRES_URL configured. These tests use only temporary
tables and synthetic, domain-neutral data; they never touch customer schemas.
"""
import os

import pytest

from datapilot.infrastructure.database.postgresql import PostgreSQLDatabaseProvider

URL = os.getenv("DATAPILOT_TEST_POSTGRES_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not URL, reason="Set DATAPILOT_TEST_POSTGRES_URL"),
]


async def test_array_membership_empty_and_distinct_expansion():
    db = PostgreSQLDatabaseProvider(URL or "")
    try:
        values = ("WITH benchmark_items(id,owner,category,tags,period) AS (VALUES "
                  "(1,'A','X',ARRAY['Alpha','Beta'],2020),"
                  "(2,'A','X',ARRAY[]::TEXT[],2021),"
                  "(3,'B','Y',NULL::TEXT[],2021),"
                  "(4,'B','Y',ARRAY['Beta'],2020),"
                  "(5,'A','X',ARRAY['Alpha','Alpha'],2021)) ")
        count = await db.execute_query(
            values + "SELECT COUNT(DISTINCT id) FROM benchmark_items "
            "WHERE COALESCE(CARDINALITY(tags),0)>0"
        )
        assert count.rows == [[3]]
        both = await db.execute_query(
            "SELECT COUNT(DISTINCT id) FROM benchmark_items "
            "WHERE tags @> ARRAY['Alpha','Beta']"
        )
        assert both.rows == [[1]]
        expanded = await db.execute_query(
            values + "SELECT t.tag, COUNT(DISTINCT b.id) "
            "FROM benchmark_items b "
            "CROSS JOIN LATERAL UNNEST(b.tags) AS t(tag) "
            "GROUP BY t.tag ORDER BY t.tag"
        )
        assert expanded.rows == [['Alpha',2],['Beta',2]]
    finally:
        await db.close()


async def test_period_comparison_does_not_split_grouping_grain():
    db = PostgreSQLDatabaseProvider(URL or "")
    try:
        values = ("WITH benchmark_periods(id,owner,period) AS (VALUES "
                  "(1,'A',2020),(2,'A',2021),(3,'A',2021),(4,'B',2020)) ")
        result = await db.execute_query(
            values + "SELECT owner, "
            "COUNT(DISTINCT CASE WHEN period=2020 THEN id END) AS p2020, "
            "COUNT(DISTINCT CASE WHEN period=2021 THEN id END) AS p2021 "
            "FROM benchmark_periods WHERE period IN (2020,2021) "
            "GROUP BY owner ORDER BY owner"
        )
        assert result.rows == [['A',1,2],['B',1,0]]
    finally:
        await db.close()
