# Query and Resource Policies

Data Pilot applies a provider-independent execution policy after SQL AST safety validation and before database execution.

## Policy controls

- timeout_seconds: maximum database statement timeout requested from the provider.
- max_result_rows: maximum result rows accepted by the orchestrator.
- max_query_length: maximum SQL text length.
- require_limit_for_non_aggregate: automatically add a bounded LIMIT to ordinary row-returning queries.
- default_limit: LIMIT applied when a non-aggregate query has none.
- max_limit: upper bound for an explicit numeric LIMIT.

## Execution flow

    SQL generator/template
        |
        v
    SQL AST safety validation
        |
        v
    Query resource policy
        |
        +--> reject oversized/invalid SQL
        +--> add bounded LIMIT
        +--> reduce excessive LIMIT
        |
        v
    Database provider
        |
        v
    result row-count check

The policy does not contain PostgreSQL-specific code. Database adapters remain responsible for implementing the actual timeout and read-only execution mechanisms.

## Why this is separate

This boundary allows future database providers to share the same resource policy while implementing engine-specific controls independently.

It also keeps future SaaS controls such as tenant quotas, usage budgets, concurrency limits, and billing out of the open-source query core until they are actually needed.