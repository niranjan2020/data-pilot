"""Persistence contract tests for provider configuration without a live database."""

import inspect

from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider


def test_ai_provider_configuration_schema_contains_no_secret_columns():
    source = inspect.getsource(PostgreSQLMetadataProvider.save_ai_provider_configuration)
    forbidden = ("api_key", "password", "secret_value", "credential")
    assert all(token not in source for token in forbidden)


def test_ai_provider_configuration_ddl_contains_no_secret_columns():
    from datapilot.infrastructure.metadata import postgresql
    ddl = postgresql._CATALOG_DDL
    table = ddl.split("CREATE TABLE IF NOT EXISTS datapilot_catalog.ai_provider_configuration", 1)[1]
    table = table.split(");", 1)[0]
    assert "api_key" not in table
    assert "password" not in table
    assert "secret" not in table
