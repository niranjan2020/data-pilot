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
