import pytest

from datapilot.application.services.analytical_publication_admin import AnalyticalPublicationAdmin
from datapilot.application.services.authorized_analytical_publication import (
    AuthorizedAnalyticalPublicationWorkflow,
)


class Repository:
    def __init__(self):
        self.grants = set()

    async def publish(self, *, data_source_id, kind, semantic_id):
        self.grants.add((data_source_id, kind, semantic_id))

    async def revoke(self, *, data_source_id, kind, semantic_id):
        self.grants.discard((data_source_id, kind, semantic_id))

    async def is_published(self, data_source_id, kind, semantic_id):
        return (data_source_id, kind, semantic_id) in self.grants


class Authorizer:
    def __init__(self, allowed):
        self.allowed = allowed
        self.calls = []

    async def can_manage_analytical_publications(self, *, principal_id, data_source_id):
        self.calls.append((principal_id, data_source_id))
        return (principal_id, data_source_id) in self.allowed


def workflow(allowed):
    repo = Repository()
    authorizer = Authorizer(allowed)
    return AuthorizedAnalyticalPublicationWorkflow(
        publication_admin=AnalyticalPublicationAdmin(repo), authorizer=authorizer,
    ), repo, authorizer


@pytest.mark.asyncio
async def test_authorized_principal_can_publish_and_read():
    service, repo, auth = workflow({("admin", 7)})
    result = await service.set_publication(
        principal_id="admin", data_source_id=7, kind="metric",
        semantic_id=2, published=True,
    )
    assert result.published is True
    assert (await service.get_publication(
        principal_id="admin", data_source_id=7, kind="metric", semantic_id=2,
    )).published is True
    assert auth.calls == [("admin", 7), ("admin", 7)]


@pytest.mark.asyncio
async def test_permission_is_datasource_scoped():
    service, repo, _ = workflow({("admin", 7)})
    with pytest.raises(PermissionError):
        await service.set_publication(
            principal_id="admin", data_source_id=8, kind="metric",
            semantic_id=2, published=True,
        )
    assert repo.grants == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("principal", ["", " ", None])
async def test_missing_principal_fails_before_authorizer(principal):
    service, repo, auth = workflow({("admin", 7)})
    with pytest.raises(PermissionError):
        await service.set_publication(
            principal_id=principal, data_source_id=7,
            kind="metric", semantic_id=2, published=True,
        )
    assert auth.calls == []


@pytest.mark.asyncio
async def test_non_boolean_authorization_does_not_grant_access():
    class InvalidAuthorizer:
        async def can_manage_analytical_publications(self, **kwargs):
            return 1

    repo = Repository()
    service = AuthorizedAnalyticalPublicationWorkflow(
        publication_admin=AnalyticalPublicationAdmin(repo),
        authorizer=InvalidAuthorizer(),
    )
    with pytest.raises(PermissionError):
        await service.get_publication(
            principal_id="admin", data_source_id=7,
            kind="metric", semantic_id=2,
        )


@pytest.mark.asyncio
async def test_authorization_error_fails_closed():
    class BrokenAuthorizer:
        async def can_manage_analytical_publications(self, **kwargs):
            raise RuntimeError("Auth backend unavailable")

    service = AuthorizedAnalyticalPublicationWorkflow(
        publication_admin=AnalyticalPublicationAdmin(Repository()),
        authorizer=BrokenAuthorizer(),
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        await service.get_publication(
            principal_id="admin", data_source_id=7,
            kind="metric", semantic_id=2,
        )


def test_missing_authorizer_is_rejected():
    with pytest.raises(ValueError, match="authorizer"):
        AuthorizedAnalyticalPublicationWorkflow(
            publication_admin=AnalyticalPublicationAdmin(Repository()),
            authorizer=None,
        )
