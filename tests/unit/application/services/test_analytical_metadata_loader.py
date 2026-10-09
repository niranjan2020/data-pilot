import pytest

from datapilot.application.services.analytical_metadata_loader import (
    load_published_analytical_context,
)


class FakeProvider:
    async def get_data_source_id(self, name):
        return 7 if name == "sales" else None

    async def list_semantic_entities(self, source_id):
        return [{"id": 1, "name": "Customer"}]

    async def list_semantic_metrics(self, source_id):
        return [{"id": 2, "name": "Revenue"}, {"id": 3, "name": "Draft Revenue"}]

    async def list_time_dimensions(self, source_id):
        return [{"id": 4, "name": "Order Date"}]


@pytest.mark.asyncio
async def test_only_authorized_catalog_records_are_exposed():
    calls = []

    async def authorize(source_id, kind, identifier):
        calls.append((source_id, kind, identifier))
        return identifier != 3

    context = await load_published_analytical_context(
        provider=FakeProvider(), datasource="sales", authorize=authorize,
    )
    assert [m["name"] for m in context.metrics] == ["Revenue"]
    assert [d["name"] for d in context.dimensions] == ["Customer"]
    assert [t["name"] for t in context.time_dimensions] == ["Order Date"]
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_no_implicit_publication_grants():
    async def deny(source_id, kind, identifier):
        return False

    context = await load_published_analytical_context(
        provider=FakeProvider(), datasource="sales", authorize=deny,
    )
    assert context.metrics == ()
    assert context.dimensions == ()
    assert context.time_dimensions == ()


@pytest.mark.asyncio
async def test_unknown_datasource_fails_closed():
    async def allow(source_id, kind, identifier):
        return True

    with pytest.raises(ValueError, match="Unknown datasource"):
        await load_published_analytical_context(
            provider=FakeProvider(), datasource="unknown", authorize=allow,
        )


@pytest.mark.asyncio
async def test_missing_authorizer_fails_closed():
    with pytest.raises(ValueError, match="authorizer"):
        await load_published_analytical_context(
            provider=FakeProvider(), datasource="sales", authorize=None,
        )


@pytest.mark.asyncio
async def test_invalid_catalog_id_is_rejected():
    class BadProvider(FakeProvider):
        async def list_semantic_metrics(self, source_id):
            return [{"id": True, "name": "Revenue"}]

    async def allow(source_id, kind, identifier):
        return True

    with pytest.raises(ValueError, match="identifier"):
        await load_published_analytical_context(
            provider=BadProvider(), datasource="sales", authorize=allow,
        )


from datapilot.application.services.analytical_metadata_loader import (
    load_persisted_analytical_context,
)


class FakePublicationStore:
    def __init__(self, allowed):
        self.allowed = allowed
        self.calls = []

    async def is_published(self, source_id, kind, semantic_id):
        self.calls.append((source_id, kind, semantic_id))
        return (source_id, kind, semantic_id) in self.allowed


@pytest.mark.asyncio
async def test_persisted_loader_uses_store_for_each_semantic_definition():
    store = FakePublicationStore({
        (7, "metric", 2),
        (7, "dimension", 1),
        (7, "time_dimension", 4),
    })
    context = await load_persisted_analytical_context(
        provider=FakeProvider(), datasource="sales", publication_store=store,
    )
    assert [item["name"] for item in context.metrics] == ["Revenue"]
    assert [item["name"] for item in context.dimensions] == ["Customer"]
    assert [item["name"] for item in context.time_dimensions] == ["Order Date"]
    assert len(store.calls) == 4


@pytest.mark.asyncio
async def test_persisted_loader_does_not_publish_unapproved_definitions():
    context = await load_persisted_analytical_context(
        provider=FakeProvider(), datasource="sales",
        publication_store=FakePublicationStore(set()),
    )
    assert context.metrics == ()
    assert context.dimensions == ()
    assert context.time_dimensions == ()


@pytest.mark.asyncio
async def test_persisted_loader_requires_publication_store():
    with pytest.raises(ValueError, match="publication store"):
        await load_persisted_analytical_context(
            provider=FakeProvider(), datasource="sales", publication_store=None,
        )


@pytest.mark.asyncio
async def test_persisted_loader_rejects_store_without_authorization_method():
    with pytest.raises(ValueError, match="publication store"):
        await load_persisted_analytical_context(
            provider=FakeProvider(), datasource="sales", publication_store=object(),
        )


@pytest.mark.asyncio
async def test_persisted_loader_propagates_authorization_failure():
    class BrokenStore:
        async def is_published(self, source_id, kind, semantic_id):
            raise RuntimeError("Publication storage unavailable")

    with pytest.raises(RuntimeError, match="unavailable"):
        await load_persisted_analytical_context(
            provider=FakeProvider(), datasource="sales", publication_store=BrokenStore(),
        )
