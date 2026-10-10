# Governed NL-to-SQL benchmark: 38 unique questions

This is a *diagnostic* regression tracker, not a product-specific ruleset.
All implementation fixes must remain metadata-driven and cross-domain.

## Baseline (2026-10-10)
- 38 unique questions (the supplied ordered/built-year batch repeats one question).
- 26 structurally acceptable; 11 incorrect or rejected; 1 governed-metric block requiring policy review.
- **No 38/38 end-to-end rerun has been performed.** No accuracy claim is implied.
- Local user reported **4/4 targeted unit tests** and **1829 existing unit tests** passing after the UNNEST recognition fix.
- 2/2 PostgreSQL read-only synthetic integration tests passed.

## Open issue register

| ID | Generic failure class | Verification needed |
|---|---|---|
| 3A-5 | Null array mistaken for populated array | Require cardinality > 0 for requested nonempty membership |
| 3A-7 | UNNEST grouped without a lateral source | Generate valid array expansion; verify cardinality |
| 3A-8 | Array element literal differs from canonical mapped value | Use published categorical mapping, exact case |
| 3B-2 | Numeric year range misclassified as categorical comparison | Inspect resolver trace and type evidence |
| 3B-4 | Ordered-vs-built comparison refers outside governed scope | Correct single-source time dimension comparison |
| 3B-9 | Numeric year range misclassified as categorical comparison | Same underlying classifier as 3B-2 |
| 3C-5 | Top-N average-age query uses unapproved source | Governed top-N subquery/CTE handling |
| 3C-6 | Top managing owners rejected by correctness checks | Inspect exact failing checks |
| 3C-10 | Listing/grouping grain does not match question | Resolve list vs aggregate intent |
| 3D-8 | Period discriminator incorrectly added to GROUP BY | One row per requested comparison dimension |
| 3D-9 | Non-null array mistaken for populated array | Same class as 3A-5 |
| 3D-7 | Percentage metric blocked by governance | Confirm whether a published governed ratio metric exists |

## Release gates

1. Each issue fixed or reclassified with a trace and explicit evidence.
2. All 38 questions rerun against the selected governed data source.
3. Real PostgreSQL tests for arrays and aggregation pass.
4. Complete unit suite passes.
5. No hardcoded domain-specific corrections; fail closed on ambiguous semantics.

## Local commands

```cmd
git pull && python -m pytest tests/unit -q
python -m pytest tests/integration/test_postgresql_array_aggregation_semantics.py -v -rs
```

Live benchmark execution requires the user's configured database, published semantic model, and Query Playground. Synthetic SQL tests alone do not validate NL-to-SQL generation.
