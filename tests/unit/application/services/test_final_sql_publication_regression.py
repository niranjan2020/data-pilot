"""Regression: SQL changed by a repair must be authorized as final SQL."""
import asyncio

from datapilot.application.published_join_authorization import authorize_published_joins


RELATIONSHIP = {
    "from_schema": "public", "from_table": "accounts", "from_column": "id",
    "to_schema": "public", "to_table": "transactions", "to_column": "account_id",
}


class PublicationCatalog:
    def __init__(self, grants):
        self.grants = grants
        self.lookups = []

    async def list_current_relationship_publications(self, source_id):
        self.lookups.append(source_id)
        return self.grants


def authorize(catalog, sql, required=None, source_id=7):
    return asyncio.run(authorize_published_joins(
        catalog, source_id, sql,
        [RELATIONSHIP] if required is None else required,
    ))


def test_repaired_join_cannot_use_missing_publication():
    catalog = PublicationCatalog([])
    sql = (
        "SELECT a.id FROM public.accounts a "
        "JOIN public.transactions t ON a.id = t.account_id"
    )
    result = authorize(catalog, sql)
    assert not result.allowed
    assert not result.verified_grants
    assert catalog.lookups == [7]


def test_repaired_join_rejects_wrong_datasource_identity():
    catalog = PublicationCatalog([RELATIONSHIP])
    sql = (
        "SELECT a.id FROM public.accounts a "
        "JOIN public.transactions t ON a.id = t.account_id"
    )
    result = authorize(catalog, sql, source_id=None)
    assert not result.allowed
    assert catalog.lookups == []


def test_repaired_join_rejects_unselected_relationship_even_with_grant():
    catalog = PublicationCatalog([RELATIONSHIP])
    sql = (
        "SELECT a.id FROM public.accounts a "
        "JOIN public.items i ON a.id = i.account_id"
    )
    result = authorize(catalog, sql)
    assert not result.allowed
