import pytest

from datapilot.application.services.analytical_publication_admin import (
    AnalyticalPublicationAdmin,
)


class FakeRepository:
    def __init__(self):
        self.grants = set()
        self.calls = []

    async def publish(self, *, data_source_id, kind, semantic_id):
        self.calls.append("publish")
        self.grants.add((data_source_id, kind, semantic_id))

    async def revoke(self, *, data_source_id, kind, semantic_id):
        self.calls.append("revoke")
        self.grants.discard((data_source_id, kind, semantic_id))

    async def is_published(self, data_source_id, kind, semantic_id):
        self.calls.append("read")
        return (data_source_id, kind, semantic_id) in self.grants


@pytest.mark.asyncio
async def test_admin_can_explicitly_publish_and_read():
    repo = FakeRepository()
    admin = AnalyticalPublicationAdmin(repo)
    result = await admin.set_publication(
        data_source_id=7, kind="metric", semantic_id=3,
        published=True, authorized=True,
    )
    assert result.published is True
    assert (await admin.get_publication(
        data_source_id=7, kind="metric", semantic_id=3, authorized=True,
    )).published is True


@pytest.mark.asyncio
async def test_admin_can_revoke_publication():
    repo = FakeRepository()
    admin = AnalyticalPublicationAdmin(repo)
    await admin.set_publication(
        data_source_id=7, kind="dimension", semantic_id=3,
        published=True, authorized=True,
    )
    result = await admin.set_publication(
        data_source_id=7, kind="dimension", semantic_id=3,
        published=False, authorized=True,
    )
    assert result.published is False
    assert repo.grants == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [False, None, 1, "true"])
async def test_non_admin_cannot_publish(authorized):
    repo = FakeRepository()
    with pytest.raises(PermissionError):
        await AnalyticalPublicationAdmin(repo).set_publication(
            data_source_id=7, kind="metric", semantic_id=3,
            published=True, authorized=authorized,
        )
    assert repo.calls == []


@pytest.mark.asyncio
async def test_non_admin_cannot_read_publication_state():
    repo = FakeRepository()
    with pytest.raises(PermissionError):
        await AnalyticalPublicationAdmin(repo).get_publication(
            data_source_id=7, kind="metric", semantic_id=3, authorized=False,
        )
    assert repo.calls == []


@pytest.mark.asyncio
async def test_invalid_publication_decision_is_rejected():
    repo = FakeRepository()
    with pytest.raises(ValueError, match="boolean"):
        await AnalyticalPublicationAdmin(repo).set_publication(
            data_source_id=7, kind="metric", semantic_id=3,
            published="yes", authorized=True,
        )
    assert repo.calls == []


@pytest.mark.asyncio
async def test_publication_failure_is_not_reported_as_success():
    class BrokenRepository(FakeRepository):
        async def publish(self, **kwargs):
            raise RuntimeError("Database unavailable")

    with pytest.raises(RuntimeError, match="unavailable"):
        await AnalyticalPublicationAdmin(BrokenRepository()).set_publication(
            data_source_id=7, kind="metric", semantic_id=3,
            published=True, authorized=True,
        )


def test_repository_is_required():
    with pytest.raises(ValueError, match="repository"):
        AnalyticalPublicationAdmin(None)
