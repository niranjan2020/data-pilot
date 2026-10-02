"""Unit tests for the schema discovery application service."""

from unittest.mock import AsyncMock

import pytest

from datapilot.application.services.schema_discovery import (
    SchemaDiscoveryOptions,
    SchemaDiscoveryService,
)
from datapilot.core.exceptions import MetadataError
from datapilot.domain.models import ColumnMetadata, ForeignKeyMetadata, SchemaMetadata, TableMetadata


class FakeDatabaseProvider:
    dialect = "postgresql"

    def __init__(self, schema: SchemaMetadata) -> None:
        self.schema = schema
        self.introspect_schema = AsyncMock(return_value=schema)


class FakeMetadataProvider:
    def __init__(self) -> None:
        self.save_schema = AsyncMock()


@pytest.fixture
def discovered_schema() -> SchemaMetadata:
    return SchemaMetadata(
        dialect="postgresql",
        tables=[
            TableMetadata(
                name="z_vessels",
                schema_name="public",
                columns=[
                    ColumnMetadata(name="IMO", data_type="integer"),
                    ColumnMetadata(name="name", data_type="text"),
                ],
                primary_keys=["IMO"],
            ),
            TableMetadata(
                name="a_operators",
                schema_name="public",
                columns=[ColumnMetadata(name="operator_id", data_type="integer")],
                foreign_keys=[
                    ForeignKeyMetadata(
                        constrained_column="operator_id",
                        referenced_table="companies",
                        referenced_column="id",
                    )
                ],
            ),
            TableMetadata(name="audit_log", schema_name="public"),
        ],
    )


@pytest.mark.asyncio
async def test_discover_normalizes_and_versions_schema(discovered_schema: SchemaMetadata) -> None:
    db = FakeDatabaseProvider(discovered_schema)
    service = SchemaDiscoveryService(db)

    result = await service.discover()

    assert [table.name for table in result.tables] == ["a_operators", "audit_log", "z_vessels"]
    assert [column.name for column in result.get_table("z_vessels").columns] == ["IMO", "name"]
    assert result.version is not None
    assert len(result.version) == 16
    db.introspect_schema.assert_awaited_once_with(None)


@pytest.mark.asyncio
async def test_discover_does_not_mutate_provider_schema(discovered_schema: SchemaMetadata) -> None:
    original = [column.name for column in discovered_schema.get_table("z_vessels").columns]
    await SchemaDiscoveryService(FakeDatabaseProvider(discovered_schema)).discover()
    assert [column.name for column in discovered_schema.get_table("z_vessels").columns] == original


@pytest.mark.asyncio
async def test_discover_can_exclude_tables(discovered_schema: SchemaMetadata) -> None:
    service = SchemaDiscoveryService(FakeDatabaseProvider(discovered_schema))

    result = await service.discover(
        SchemaDiscoveryOptions(excluded_tables=frozenset({"AUDIT_LOG"}))
    )

    assert [table.name for table in result.tables] == ["a_operators", "z_vessels"]


@pytest.mark.asyncio
async def test_refresh_persists_catalog(discovered_schema: SchemaMetadata) -> None:
    metadata = FakeMetadataProvider()
    service = SchemaDiscoveryService(FakeDatabaseProvider(discovered_schema), metadata)

    result = await service.refresh()

    metadata.save_schema.assert_awaited_once_with(result)


@pytest.mark.asyncio
async def test_persist_requires_metadata_provider(discovered_schema: SchemaMetadata) -> None:
    service = SchemaDiscoveryService(FakeDatabaseProvider(discovered_schema))

    with pytest.raises(MetadataError):
        await service.discover(persist=True)


@pytest.mark.asyncio
async def test_same_schema_produces_same_version(discovered_schema: SchemaMetadata) -> None:
    first = await SchemaDiscoveryService(FakeDatabaseProvider(discovered_schema)).discover()
    second = await SchemaDiscoveryService(FakeDatabaseProvider(discovered_schema)).discover()

    assert first.version == second.version
