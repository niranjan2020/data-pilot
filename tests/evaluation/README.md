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


## Running the semantic regression suite

Run the semantic suite from the repository root with the same environment used by the API:

```bash
python -m tests.evaluation.run_semantic
```

Use another case file when needed:

```bash
python -m tests.evaluation.run_semantic --cases tests/evaluation/semantic_cases.json
```

The runner composes the normal Data Pilot adapters directly, so it exercises Qdrant retrieval, authoritative PostgreSQL semantic context, schema pruning, SQL generation, validation, policy enforcement, and database execution. It does not call the HTTP API and does not duplicate query logic.

Each case prints `PASS` or `FAIL` with failure reasons. The process exits with code 0 only when every case passes; any failure returns code 1 so the command can later be used unchanged in CI.

The semantic suite requires the configured source database, metadata PostgreSQL, Qdrant, embedding model, and current LLM provider credentials to be available. Expected answers remain evaluator-only and are never supplied to the SQL generator.


## Promoting real usage into regression cases

A reproducible OSS issue or field failure may be promoted into the evaluation corpus without changing runtime query models. Regression metadata is evaluator-only and supports two optional objects:

- `provenance`: `origin`, `reference`, `discovered_version`, and `promoted_reason`.
- `reproduction`: `dialect`, `provider`, `fixture`, and concise `notes`.

Existing curated cases remain valid without either object. A promoted case should contain the smallest question, governed fixture/configuration, and deterministic expectation that reproduces the failure. Do not copy customer data, credentials, proprietary schema names, raw prompts, or sensitive query results into the repository. Generalize the reproducer to a safe fixture whenever possible.

Example:

```json
{
  "id": "grouping-regression-001",
  "question": "Show revenue by region",
  "provenance": {
    "origin": "oss_issue",
    "reference": "issue-123",
    "discovered_version": "0.1.0",
    "promoted_reason": "Required grouping dimension was omitted."
  },
  "reproduction": {
    "dialect": "postgresql",
    "provider": "postgresql",
    "fixture": "tests/fixtures/postgresql"
  },
  "expected": {
    "require_completed": true,
    "required_correctness_codes": ["grouping_dimension_alignment"]
  }
}
```

Provenance explains why a regression exists; it must never alter query execution or expected behavior. Reproduction metadata records how to recreate the incident but is likewise not supplied to SQL generation.


## Regression contribution workflow

When an OSS report exposes a query-quality failure, promote it only when the behavior is reproducible and the expected outcome can be stated deterministically.

1. **Reproduce first.** Confirm the failure against a supported fixture or create the smallest safe generic fixture needed to reproduce it.
2. **Sanitize the reproducer.** Remove customer data, credentials, proprietary identifiers, sensitive results, and unnecessary schema detail. Prefer generic entities such as customers, orders, and products.
3. **Choose the narrowest durable layer.**
   - Deterministic engine behavior belongs in unit/fixture tests.
   - Semantic selection or end-to-end configured-source behavior belongs in an evaluation case.
   - Provider-specific behavior belongs in provider integration tests.
4. **Record provenance.** Add `provenance.origin`, a non-sensitive issue/reference when available, the version where the failure was observed, and a concise reason the case is worth retaining.
5. **Record reproduction facts.** Add only the dialect/provider/fixture/notes required to recreate the behavior. These fields are documentation and must not influence orchestration.
6. **Assert behavior, not an implementation accident.** Prefer status, governed objects, correctness codes, SQL invariants, clarification, rejection, and deterministic result assertions. Avoid exact generated SQL unless exact text is itself the contract.
7. **Prove the regression.** When practical, verify the new test/case fails before the fix and passes after it.
8. **Run the relevant focused gate, then the full automated suite.** Changes that affect live semantic behavior must also preserve the unchanged live benchmark.

A regression case should be rejected during review if it cannot be reproduced, contains sensitive/proprietary material, weakens an existing expectation merely to make a failure pass, duplicates an existing case without adding coverage, or encodes source-specific semantics in core runtime code.

### Review checklist

- [ ] Stable, unique case/test identifier.
- [ ] Minimal sanitized question and fixture/configuration.
- [ ] Deterministic expectation that captures the original failure.
- [ ] Provenance explains why the regression exists.
- [ ] Reproduction metadata is sufficient but non-sensitive.
- [ ] No evaluator ground truth is supplied to SQL generation.
- [ ] No customer credentials/data or proprietary schema details are committed.
- [ ] Correct test layer chosen.
- [ ] Focused regression tests pass.
- [ ] Full automated suite passes.
- [ ] Live semantic benchmark remains unchanged when the change can affect it.
