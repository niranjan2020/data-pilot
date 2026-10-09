import pytest

from datapilot.infrastructure.metadata.analytical_publications import (
    ANALYTICAL_PUBLICATION_DDL, AnalyticalPublicationStore, publication_table_for,
)


@pytest.mark.parametrize("kind,table", [
    ("metric", "semantic_metrics"),
    ("dimension", "semantic_entities"),
    ("time_dimension", "semantic_time_dimensions"),
])
def test_kind_uses_whitelisted_catalog_table(kind, table):
    assert publication_table_for(kind).endswith(table)


@pytest.mark.parametrize("kind", ["unknown", "metric; DROP TABLE x", "", None])
def test_unsupported_kind_fails_closed(kind):
    with pytest.raises(ValueError, match="Unsupported"):
        publication_table_for(kind)


def test_publication_schema_has_scoped_composite_key_and_no_default_grants():
    assert "PRIMARY KEY (data_source_id, semantic_kind, semantic_id)" in ANALYTICAL_PUBLICATION_DDL
    assert "REFERENCES datapilot_catalog.data_sources(id)" in ANALYTICAL_PUBLICATION_DDL
    assert "DEFAULT TRUE" not in ANALYTICAL_PUBLICATION_DDL


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


@pytest.mark.asyncio
async def test_publish_requires_existing_definition_with_matching_source():
    cursor = Cursor(exists=False)
    store = AnalyticalPublicationStore(Provider(cursor))
    with pytest.raises(ValueError, match="does not belong"):
        await store.publish(data_source_id=7, kind="metric", semantic_id=3)
    assert not any("INSERT INTO" in q for q, _ in cursor.queries)


@pytest.mark.asyncio
async def test_publication_uses_parameterized_ids_and_approved_table():
    cursor = Cursor()
    store = AnalyticalPublicationStore(Provider(cursor))
    await store.publish(data_source_id=7, kind="metric", semantic_id=3)
    assert cursor.queries[-1][1] == (7, "metric", 3)
    assert "semantic_metrics" in cursor.queries[-2][0]


@pytest.mark.asyncio
async def test_revoke_is_scoped_to_source_kind_and_id():
    cursor = Cursor()
    await AnalyticalPublicationStore(Provider(cursor)).revoke(
        data_source_id=7, kind="metric", semantic_id=3,
    )
    assert cursor.queries[-1][1] == (7, "metric", 3)


@pytest.mark.asyncio
async def test_authorization_rechecks_definition_ownership():
    cursor = Cursor(exists=False)
    published = await AnalyticalPublicationStore(Provider(cursor)).is_published(
        7, "metric", 3,
    )
    assert published is False
    assert cursor.queries[-1][1] == (7, "metric", 3, 7)


@pytest.mark.asyncio
async def test_invalid_identifiers_rejected_before_db():
    store = AnalyticalPublicationStore(Provider(Cursor()))
    with pytest.raises(ValueError, match="datasource"):
        await store.is_published(True, "metric", 3)
    with pytest.raises(ValueError, match="semantic"):
        await store.publish(data_source_id=7, kind="metric", semantic_id=0)
