import pytest

from datapilot.infrastructure.database.relationship_integrity import verify_referential_integrity


class Cursor:
    def __init__(self, results):
        self.results = iter(results)
        self.queries = []

    async def execute(self, query):
        self.queries.append(query)

    async def fetchone(self):
        return (next(self.results),)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class Connection:
    def __init__(self, results):
        self.statements = []
        self.current_cursor = Cursor(results)

    async def execute(self, query):
        self.statements.append(query)

    def cursor(self):
        return self.current_cursor

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class Pool:
    def __init__(self, results):
        self.conn = Connection(results)

    def connection(self):
        return self.conn


class Provider:
    def __init__(self, results):
        self.pool = Pool(results)

    async def _get_pool(self):
        return self.pool


def review():
    return dict(from_schema="demo", from_table="events", from_column="asset_id",
                to_schema="demo", to_table="assets", to_column="id")


@pytest.mark.asyncio
@pytest.mark.parametrize("results,expected_null,expected_unmatched", [
    ([False, False], False, False),
    ([True, False], True, False),
    ([False, True], False, True),
    ([True, True], True, True),
])
async def test_null_and_unmatched_are_distinct(results, expected_null, expected_unmatched):
    provider = Provider(results)
    evidence = await verify_referential_integrity(provider, review())
    assert evidence.checked
    assert evidence.nullable_references is expected_null
    assert evidence.unmatched_references is expected_unmatched
    assert evidence.publishable is False
    assert "REPEATABLE READ, READ ONLY" in provider.pool.conn.statements[0]
    assert "statement_timeout" in provider.pool.conn.statements[1]
    assert "NOT EXISTS" in provider.pool.conn.current_cursor.queries[1]


@pytest.mark.asyncio
async def test_database_failure_is_not_a_success():
    class Broken:
        async def _get_pool(self):
            raise RuntimeError("private credential")
    evidence = await verify_referential_integrity(Broken(), review())
    assert not evidence.checked and not evidence.publishable
    assert "credential" not in evidence.reason


@pytest.mark.asyncio
async def test_unsafe_identifier_is_rejected():
    item = review()
    item["from_table"] = "events;delete"
    with pytest.raises(ValueError):
        await verify_referential_integrity(Provider([False, False]), item)
