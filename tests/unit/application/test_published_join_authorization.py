"""Fail-closed authorization regression coverage."""
from types import SimpleNamespace
import pytest
from unittest.mock import patch

from datapilot.application.published_join_authorization import authorize_published_joins


R = dict(from_schema="sales", from_table="orders", from_column="customer_id",
         to_schema="sales", to_table="customers", to_column="id",
         join_policy="matched_only", cardinality="many_to_one",
         review_status="approved")
SQL = "SELECT * FROM sales.orders o INNER JOIN sales.customers c ON o.customer_id = c.id"


class Metadata:
    def __init__(self, grants):
        self.grants = grants
        self.calls = 0

    async def list_current_relationship_publications(self, source_id):
        self.calls += 1
        return self.grants


@pytest.mark.asyncio
async def test_authorized_sql_requires_actual_join_validation():
    meta = Metadata([R])
    with patch("datapilot.application.published_join_authorization.validate_governed_join_graph",
               return_value=SimpleNamespace(allowed=True, reasons=())) as validator:
        result = await authorize_published_joins(meta, 1, SQL, [R])
    assert result.allowed
    validator.assert_called_once_with(SQL, [R])
    assert meta.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("grants", [[], [R, R], None, [{}]])
async def test_missing_ambiguous_or_invalid_grants_fail(grants):
    meta = Metadata(grants)
    result = await authorize_published_joins(meta, 1, SQL, [R])
    assert not result.allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [None, 0, -1, True, "1"])
async def test_invalid_source_never_reads_catalog(source):
    meta = Metadata([R])
    result = await authorize_published_joins(meta, source, SQL, [R])
    assert not result.allowed
    assert meta.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("sql", [None, "", " ", 123])
async def test_invalid_sql_fails_before_catalog(sql):
    meta = Metadata([R])
    result = await authorize_published_joins(meta, 1, sql, [R])
    assert not result.allowed
    assert meta.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("relationships", [[], [{}], [R, R], [None]])
async def test_invalid_relationships_fail(relationships):
    meta = Metadata([R])
    result = await authorize_published_joins(meta, 1, SQL, relationships)
    assert not result.allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("key,value", [
    ("from_schema", "other"), ("from_table", "other"),
    ("from_column", "other"), ("to_schema", "other"),
    ("to_table", "other"), ("to_column", "other"),
])
async def test_identity_mismatch_fails(key, value):
    meta = Metadata([R])
    result = await authorize_published_joins(meta, 1, SQL, [{**R, key: value}])
    assert not result.allowed


@pytest.mark.asyncio
async def test_actual_sql_policy_failure_is_rejected():
    meta = Metadata([R])
    with patch("datapilot.application.published_join_authorization.validate_governed_join_graph",
               return_value=SimpleNamespace(allowed=False, reasons=("Wrong join type.",))):
        result = await authorize_published_joins(meta, 1, SQL, [R])
    assert not result.allowed
    assert result.reasons == ("Wrong join type.",)
