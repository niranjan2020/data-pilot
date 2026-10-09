import pytest

from datapilot.infrastructure.metadata.analytical_attribute_publications import (
    ATTRIBUTE_DIMENSION_PUBLICATION_DDL,
    AnalyticalAttributePublicationStore,
)


class Cursor:
    def __init__(self, exists=True):
        self.exists = exists
        self.queries = []

    async def execute(self, query, params=None):
        self.queries.append((query, params))

    async def fetchone(self):
        return (1,) if self.exists else None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class Pool:
    def __init__(self, cursor):
        self._connection = Connection(cursor)

    def connection(self):
        return self._connection


class Provider:
    def __init__(self, cursor):
        self._pool = Pool(cursor)

    async def initialize(self):
        pass

    async def _get_pool(self):
        return self._pool


def test_attribute_grants_are_not_entity_grants():
    assert "PRIMARY KEY (data_source_id, entity_id, attribute_name)" in ATTRIBUTE_DIMENSION_PUBLICATION_DDL


@pytest.mark.asyncio
async def test_publish_requires_real_attribute_on_scoped_entity():
    cursor = Cursor(False)
    with pytest.raises(ValueError, match="does not belong"):
        await AnalyticalAttributePublicationStore(Provider(cursor)).publish(
            data_source_id=7, entity_id=2, attribute_name="Region",
        )
    assert not any("INSERT INTO" in q for q, _ in cursor.queries)


@pytest.mark.asyncio
async def test_publish_uses_attribute_identity():
    cursor = Cursor()
    await AnalyticalAttributePublicationStore(Provider(cursor)).publish(
        data_source_id=7, entity_id=2, attribute_name="Region",
    )
    assert cursor.queries[-1][1] == (7, 2, "Region")


@pytest.mark.asyncio
async def test_revoke_only_selected_attribute():
    cursor = Cursor()
    await AnalyticalAttributePublicationStore(Provider(cursor)).revoke(
        data_source_id=7, entity_id=2, attribute_name="Region",
    )
    assert cursor.queries[-1][1] == (7, 2, "Region")


@pytest.mark.asyncio
async def test_stale_attribute_grant_is_not_authorized():
    cursor = Cursor(False)
    assert await AnalyticalAttributePublicationStore(Provider(cursor)).is_published(
        7, 2, "Region",
    ) is False
    assert "JOIN datapilot_catalog.semantic_attributes" in cursor.queries[-1][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("entity_id,attribute", [(0, "Region"), (2, ""), (True, "Region")])
async def test_invalid_attribute_identity_is_rejected(entity_id, attribute):
    with pytest.raises(ValueError):
        await AnalyticalAttributePublicationStore(Provider(Cursor())).publish(
            data_source_id=7, entity_id=entity_id, attribute_name=attribute,
        )
