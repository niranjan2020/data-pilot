# Data Pilot evaluation dataset

This dataset is deliberately generic and provider-independent. It exists to evaluate the complete Data Pilot pipeline without making query templates part of the product architecture.

## Fixture

`tests/fixtures/postgresql/schema.sql` creates a small customers/products/orders schema.
`tests/fixtures/postgresql/seed.sql` inserts deterministic data whose answers are known in advance.

When local infrastructure is introduced, load both files into the development PostgreSQL instance. The fixture does not require Qdrant and does not prescribe Docker, Rancher Desktop, or any other runtime.

## Evaluation cases

`cases.json` contains natural-language questions and expected outcomes. Expected values are evaluator-only ground truth: they must never be supplied to SQL generation.

The intended evaluation flow is:

question -> semantic resolution -> SQL generation -> AST safety -> resource policy -> PostgreSQL -> result -> evaluation

The first cases cover filtering, aggregation, joins, grouping and ranking. Ambiguity and failure-mode cases can be added once the end-to-end runner is wired to PostgreSQL.

No saved query/template is required to answer these cases.


## Semantic retrieval evaluation

`semantic_cases.json` is the first governed-context regression suite for a configured AdventureWorks source. Unlike `cases.json`, these cases primarily validate the semantic decisions captured in `QueryResponse.trace`.

Each case can assert:
- required datasets, entities, relationships, and metrics;
- semantic objects that must not leak into the governed context;
- completed query status and SQL generation;
- result ground truth only when the source data supports a deterministic assertion.

The evaluator deliberately separates these dimensions. A query can generate valid SQL and execute successfully while still returning unusable source data; conversely, retrieval can be wrong even when the database happens to accept the SQL.

The initial suite contains revenue-by-product, units-sold-by-product, and a multi-metric product question. Add cases incrementally as semantic configuration is introduced rather than encoding AdventureWorks-specific behavior in the engine.
