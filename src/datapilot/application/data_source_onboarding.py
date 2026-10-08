"""PostgreSQL onboarding connectivity check; credentials never enter metadata."""

from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr
from psycopg.conninfo import make_conninfo

from datapilot.infrastructure.database.postgresql import PostgreSQLDatabaseProvider


class PostgreSQLConnectionInput(BaseModel):
    name: str = Field(min_length=1)
    host: str = Field(min_length=1)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1)
    username: str = Field(min_length=1)
    password: SecretStr
    sslmode: str = "prefer"


async def test_postgresql_connection(input: PostgreSQLConnectionInput) -> bool:
    """Perform an actual bounded read-only connection test; do not persist input."""
    if input.sslmode not in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}:
        raise ValueError("Unsupported PostgreSQL SSL mode")
    url = make_conninfo(
        host=input.host,
        port=input.port,
        dbname=input.database,
        user=input.username,
        password=input.password.get_secret_value(),
        sslmode=input.sslmode,
        connect_timeout=5,
        options="-c default_transaction_read_only=on",
    )
    provider = PostgreSQLDatabaseProvider(url, pool_size=1, default_timeout_seconds=7)
    try:
        return await provider.ping()
    finally:
        await provider.close()
