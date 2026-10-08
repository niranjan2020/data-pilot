import pytest

from datapilot.infrastructure.database.relationship_cardinality import (
    _qualified, verify_live_cardinality,
)


class Cursor:
    def __init__(self, duplicates=False):
        self.duplicates = duplicates
        self.statements = []

    async def execute(self, sql):
        self.statements.append(sql)

    async def fetchone(self):
        return (self.duplicates,)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class Connection:
    def __init__(self, duplicates=False):
        self.cursor_instance = Cursor(duplicates)
        self.statements = []

    def transaction(self):
        return Transaction()

    async def execute(self, sql):
        self.statements.append(sql)

    def cursor(self):
        return self.cursor_instance


class Pool:
    def __init__(self, duplicates=False):
        self.connection_instance = Connection(duplicates)

    class Context:
        def __init__(self, connection):
            self.connection_instance = connection

        async def __aenter__(self):
            return self.connection_instance

        async def __aexit__(self, *args):
            pass

    def connection(self):
        return self.Context(self.connection_instance)


class Provider:
    def __init__(self, duplicates=False):
        self.pool = Pool(duplicates)

    async def _get_pool(self):
        return self.pool


def relationship(cardinality="many_to_one"):
    return dict(from_schema="demo", from_table="events", from_column="asset_id",
                to_schema="demo", to_table="assets", to_column="id",
                cardinality=cardinality)


@pytest.mark.asyncio
async def test_live_unique_target_remains_unpublished():
    provider = Provider()
    evidence = await verify_live_cardinality(provider, relationship())
    assert evidence.checked and evidence.cardinality_holds and not evidence.publishable
    assert "READ ONLY" in provider.pool.connection_instance.statements[0]
    assert "statement_timeout" in provider.pool.connection_instance.statements[1]
    assert '"demo"."assets"' in provider.pool.connection_instance.cursor_instance.statements[0]


@pytest.mark.asyncio
async def test_live_duplicates_fail_cardinality():
    evidence = await verify_live_cardinality(Provider(True), relationship())
    assert evidence.checked and not evidence.cardinality_holds and not evidence.publishable


@pytest.mark.asyncio
async def test_many_to_many_is_denied():
    evidence = await verify_live_cardinality(Provider(), relationship("many_to_many"))
    assert not evidence.checked and not evidence.publishable


@pytest.mark.asyncio
async def test_provider_failure_is_fail_closed():
    class Broken:
        async def _get_pool(self):
            raise RuntimeError("connection secret")
    evidence = await verify_live_cardinality(Broken(), relationship())
    assert not evidence.checked and "secret" not in evidence.reason


@pytest.mark.asyncio
async def test_identifier_injection_is_denied():
    item = relationship()
    item["to_table"] = 'assets; DROP TABLE demo.events'
    with pytest.raises(ValueError):
        await verify_live_cardinality(Provider(), item)


def test_quoted_identifiers():
    assert _qualified("demo", "assets", "id") == ('"demo"."assets"', '"id"')
