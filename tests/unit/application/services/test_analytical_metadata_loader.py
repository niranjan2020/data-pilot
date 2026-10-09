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
