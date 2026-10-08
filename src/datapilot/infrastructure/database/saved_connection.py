"""Compose a saved customer PostgreSQL connection from metadata and local secrets."""
from __future__ import annotations

from psycopg.conninfo import make_conninfo

from datapilot.infrastructure.database.postgresql import PostgreSQLDatabaseProvider


async def open_saved_data_source(metadata, secret_store, source_id: int):
    """Caller owns the returned provider and must close it."""
    record = await metadata.get_data_source(source_id)
    if record is None or record["provider"] != "postgresql":
        raise ValueError("Saved PostgreSQL datasource not found")
    password = secret_store.resolve_for_runtime(source_id)
    if password is None:
        raise ValueError("Saved datasource credential unavailable")
    conninfo = make_conninfo(
        host=record["host"], port=record["port"], dbname=record["database"],
        user=record["username"], password=password, sslmode=record["sslmode"],
        connect_timeout=5, options="-c default_transaction_read_only=on",
    )
    return PostgreSQLDatabaseProvider(conninfo, pool_size=1, default_timeout_seconds=10)
