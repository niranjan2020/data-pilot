"""Administrative data-source endpoints used by the local Admin Studio."""

from __future__ import annotations

from typing import List, Literal
import hashlib
import json

from datapilot.core.config import get_settings
from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider

from fastapi import APIRouter
from pydantic import BaseModel, Field, SecretStr

from datapilot.domain.models import SchemaMetadata
from datapilot.infrastructure.database.postgresql import PostgreSQLDatabaseProvider

router = APIRouter(prefix="/api/admin/data-sources", tags=["Admin - Data Sources"])


class PostgreSQLConnectionRequest(BaseModel):
    name: str = Field(default="PostgreSQL", min_length=1)
    host: str = Field(min_length=1)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1)
    username: str = Field(min_length=1)
    password: SecretStr
    sslmode: Literal["disable", "prefer", "require"] = "prefer"

    def database_url(self) -> str:
        from urllib.parse import quote_plus
        user = quote_plus(self.username)
        password = quote_plus(self.password.get_secret_value())
        host = self.host.strip()
        database = quote_plus(self.database)
        return f"postgresql://{user}:{password}@{host}:{self.port}/{database}?sslmode={self.sslmode}"


class ConnectionTestResponse(BaseModel):
    success: bool
    message: str


class SchemaDiscoveryResponse(BaseModel):
    source_name: str
    schemas: List[SchemaMetadata]
    persisted: bool = False


async def _provider(payload: PostgreSQLConnectionRequest) -> PostgreSQLDatabaseProvider:
    return PostgreSQLDatabaseProvider(payload.database_url(), pool_size=2, default_timeout_seconds=10.0)


@router.post("/test", response_model=ConnectionTestResponse)
async def test_postgresql_connection(payload: PostgreSQLConnectionRequest) -> ConnectionTestResponse:
    provider = await _provider(payload)
    try:
        success = await provider.ping()
        return ConnectionTestResponse(
            success=success,
            message="Connection successful" if success else "Connection failed",
        )
    finally:
        await provider.close()


@router.post("/discover", response_model=SchemaDiscoveryResponse)
async def discover_postgresql_schema(payload: PostgreSQLConnectionRequest) -> SchemaDiscoveryResponse:
    provider = await _provider(payload)
    try:
        schema_names = await provider.list_schemas()
        schemas = [await provider.introspect_schema(name) for name in schema_names]

        settings = get_settings()
        metadata_url = settings.metadata_database_url
        if not metadata_url:
            return SchemaDiscoveryResponse(source_name=payload.name, schemas=schemas, persisted=False)

        metadata = PostgreSQLMetadataProvider(
            metadata_url,
            pool_size=settings.metadata_database_pool_size,
        )
        try:
            await metadata.save_data_source(
                name=payload.name,
                provider="postgresql",
                host=payload.host,
                port=payload.port,
                database_name=payload.database,
                username=payload.username,
                sslmode=payload.sslmode,
            )
            for schema in schemas:
                canonical = schema.model_dump(mode="json", exclude={"version"})
                schema.version = hashlib.sha256(
                    json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                await metadata.save_schema(schema)
            return SchemaDiscoveryResponse(source_name=payload.name, schemas=schemas, persisted=True)
        finally:
            await metadata.close()
    finally:
        await provider.close()
