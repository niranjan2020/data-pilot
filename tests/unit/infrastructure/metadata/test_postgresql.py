"""Unit tests for the PostgreSQL metadata catalog adapter."""

import pytest

from datapilot.core.exceptions import DatabaseConnectionError, MetadataError
from datapilot.domain.models import SchemaMetadata, TableMetadata
from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider


def test_metadata_provider_requires_database_url() -> None:
    with pytest.raises(DatabaseConnectionError):
        PostgreSQLMetadataProvider("")


def test_schema_name_prefers_explicit_schema() -> None:
    schema = SchemaMetadata(
        schema_name="analytics",
        tables=[TableMetadata(name="vessels", schema_name="public")],
    )
    assert PostgreSQLMetadataProvider._schema_name(schema) == "analytics"


def test_schema_name_is_inferred_when_single_table_schema_exists() -> None:
    schema = SchemaMetadata(tables=[TableMetadata(name="vessels", schema_name="analytics")])
    assert PostgreSQLMetadataProvider._schema_name(schema) == "analytics"


def test_schema_name_defaults_to_public_for_mixed_or_missing_tables() -> None:
    assert PostgreSQLMetadataProvider._schema_name(SchemaMetadata()) == "public"
    schema = SchemaMetadata(
        tables=[
            TableMetadata(name="a", schema_name="analytics"),
            TableMetadata(name="b", schema_name="reporting"),
        ]
    )
    assert PostgreSQLMetadataProvider._schema_name(schema) == "public"


@pytest.mark.asyncio
async def test_save_schema_requires_version() -> None:
    provider = PostgreSQLMetadataProvider("postgresql://example")
    schema = SchemaMetadata(tables=[TableMetadata(name="vessels")])
    with pytest.raises(MetadataError):
        await provider.save_schema(schema)


def test_catalog_ddl_contains_versioned_snapshot_tables() -> None:
    from datapilot.infrastructure.metadata.postgresql import _CATALOG_DDL

    assert "datapilot_catalog.schema_snapshots" in _CATALOG_DDL
    assert "UNIQUE (data_source_id, schema_name, version)" in _CATALOG_DDL
    assert "datapilot_catalog.columns" in _CATALOG_DDL
    assert "datapilot_catalog.foreign_keys" in _CATALOG_DDL
    assert "JSONB" in _CATALOG_DDL
