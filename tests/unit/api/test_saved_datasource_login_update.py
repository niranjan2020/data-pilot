"""Regression coverage for safe datasource login replacement."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from datapilot.api.routes import setup


class FakeSecrets:
    def __init__(self):
        self.value = "original-secret"
        self.writes = []

    def resolve_for_runtime(self, source_id):
        return self.value

    def put(self, source_id, password):
        self.writes.append(password)
        self.value = password


@pytest.fixture
def login_context(monkeypatch):
    record = {
        "id": 7, "name": "astra-dev", "provider": "postgresql",
        "host": "db.example.test", "port": 5432, "database": "astra-dev",
        "username": "original-user", "sslmode": "prefer",
    }
    metadata = SimpleNamespace(
        get_data_source=AsyncMock(return_value=record),
        update_data_source_username=AsyncMock(),
    )
    secrets = FakeSecrets()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(data_source_secret_store=secrets)))
    monkeypatch.setattr(setup, "_setup_metadata", AsyncMock(return_value=(metadata, False)))
    return record, metadata, secrets, request


@pytest.mark.asyncio
async def test_invalid_login_preserves_both_credentials_and_metadata(monkeypatch, login_context):
    record, metadata, secrets, request = login_context
    async def reject(connection):
        assert connection.host == record["host"]
        assert connection.database == record["database"]
        assert connection.username == "bad-user"
        assert connection.sslmode == record["sslmode"]
        assert connection.password.get_secret_value() == "bad-secret"
        return False
    monkeypatch.setattr(setup, "test_postgresql_connection", reject)
    with pytest.raises(HTTPException) as error:
        await setup.update_saved_data_source_login(
            7, setup.DataSourceLoginUpdate(username="bad-user", password=SecretStr("bad-secret")), request
        )
    assert error.value.status_code == 422
    metadata.update_data_source_username.assert_not_awaited()
    assert secrets.value == "original-secret"
    assert secrets.writes == []
    assert "bad-secret" not in str(error.value.detail)


@pytest.mark.asyncio
async def test_successful_login_updates_only_username_and_secret(monkeypatch, login_context):
    _, metadata, secrets, request = login_context
    monkeypatch.setattr(setup, "test_postgresql_connection", AsyncMock(return_value=True))
    result = await setup.update_saved_data_source_login(
        7, setup.DataSourceLoginUpdate(username="new-user", password=SecretStr("new-secret")), request
    )
    assert result == {"updated": True, "connected": True}
    metadata.update_data_source_username.assert_awaited_once_with(7, "new-user")
    assert secrets.value == "new-secret"
    assert "new-secret" not in str(result)


@pytest.mark.asyncio
async def test_secret_write_failure_restores_old_username(monkeypatch, login_context):
    _, metadata, secrets, request = login_context
    monkeypatch.setattr(setup, "test_postgresql_connection", AsyncMock(return_value=True))
    def fail_once(source_id, password):
        if password == "new-secret":
            raise OSError("write failed")
        secrets.value = password
    secrets.put = fail_once
    with pytest.raises(HTTPException) as error:
        await setup.update_saved_data_source_login(
            7, setup.DataSourceLoginUpdate(username="new-user", password=SecretStr("new-secret")), request
        )
    assert error.value.status_code == 503
    assert metadata.update_data_source_username.await_args_list[0].args == (7, "new-user")
    assert metadata.update_data_source_username.await_args_list[1].args == (7, "original-user")
    assert secrets.value == "original-secret"
