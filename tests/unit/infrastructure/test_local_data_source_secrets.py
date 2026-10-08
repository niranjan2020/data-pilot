"""Encrypted local datasource secret-store regressions."""
from cryptography.fernet import Fernet
from datapilot.infrastructure.secrets.local_data_source import LocalDataSourceSecretStore


def test_local_datasource_password_survives_restart_without_plaintext(tmp_path):
    store = LocalDataSourceSecretStore(str(tmp_path))
    store.put(7, "a-private-password")
    assert store.resolve_for_runtime(7) == "a-private-password"
    assert LocalDataSourceSecretStore(str(tmp_path)).resolve_for_runtime(7) == "a-private-password"
    assert b"a-private-password" not in (tmp_path / "datasource-7.enc").read_bytes()
    assert (tmp_path / "datasource.key").read_bytes() != b"a-private-password"


def test_datasource_secrets_are_isolated_by_id(tmp_path):
    store = LocalDataSourceSecretStore(str(tmp_path))
    store.put(1, "first")
    store.put(2, "second")
    assert store.resolve_for_runtime(1) == "first"
    assert store.resolve_for_runtime(2) == "second"
    assert store.resolve_for_runtime(3) is None
