# Schema Discovery

## Purpose

Schema discovery is the deterministic boundary between a customer's database and Data Pilot's semantic layer.

The discovery service does **not** call an LLM. It retrieves structural metadata from a `DatabaseProvider`, normalizes it, generates a stable catalog version, and can persist the result through `MetadataProvider`.

## Flow

```text
Connected database
       |
       v
DatabaseProvider.introspect_schema()
       |
       v
SchemaDiscoveryService
  - filter excluded tables
  - normalize ordering
  - normalize relationships
  - calculate catalog version
       |
       +----> SchemaMetadata
       |
       +----> MetadataProvider (optional persistence)
```

## Catalog version

The service serializes the normalized schema into canonical JSON and calculates a SHA-256 hash. The first 16 hexadecimal characters are stored as `SchemaMetadata.version`.

This is a **structural snapshot identifier**, not a database migration version. A change to table, column, primary-key, foreign-key, or dialect metadata will produce a different version.

## Why this is deterministic

LLMs should eventually help Data Pilot understand business meaning, but they should not decide whether a database column exists or whether two schema snapshots are structurally identical. Keeping this phase deterministic gives later semantic components a stable input and makes tests reproducible.

## Current exclusions

`SchemaDiscoveryOptions` supports:

- exact table exclusions, case-insensitive
- regular-expression table exclusions
- selecting a database schema/namespace through `schema_name`

Additional controls such as column exclusions, sample-value policies, row-count statistics, and sensitive-data detection should be added only after the catalog persistence layer is established.
