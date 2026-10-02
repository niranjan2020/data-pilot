# Metadata Catalog Persistence

Data Pilot now includes a PostgreSQL implementation of the `MetadataProvider` protocol.

## Purpose

The catalog is the durable representation of discovered database structure. It is deliberately separate from the customer/query database abstraction so the semantic layer can later enrich tables and columns with business definitions, synonyms, metrics, and rules.

For local development, `METADATA_DATABASE_URL` may be omitted and the same PostgreSQL instance can be used for both the target database and the catalog. A deployment can provide a separate metadata database without changing application/domain contracts.

## Storage model

The adapter creates a `datapilot_catalog` schema containing:

- `schema_snapshots` — immutable structural snapshots keyed by `(schema_name, version)`.
- `tables` — table/view metadata belonging to a snapshot.
- `columns` — column types, nullability, primary-key flags, descriptions, and optional sample values.
- `foreign_keys` — relational links discovered from the source database.

A new schema version creates a new snapshot. Re-saving an identical version is idempotent. This preserves historical catalog state for future change detection and semantic migration workflows.

## Usage

```python
from datapilot.infrastructure.metadata import PostgreSQLMetadataProvider

provider = PostgreSQLMetadataProvider(
    database_url="postgresql://postgres:postgres@localhost:5432/datapilot"
)

await provider.initialize()
await provider.save_schema(schema)
latest = await provider.get_schema("public")
await provider.close()
```

`SchemaDiscoveryService.refresh()` can use this provider through the existing `MetadataProvider` protocol.

## Configuration

```text
DEFAULT_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/datapilot
METADATA_DATABASE_URL=
METADATA_DATABASE_POOL_SIZE=3
```

If `METADATA_DATABASE_URL` is empty, application wiring can fall back to `DEFAULT_DATABASE_URL`. Credentials for customer databases are not stored by this catalog adapter.

## Deliberate scope

This phase does not introduce tenants, users, billing, authentication, LLM calls, embeddings, or semantic business-rule tables. Those belong to later layers and can build on this stable catalog boundary.
