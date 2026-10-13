# Data Pilot architecture and Wren capability-gap audit — 2026-10-13

Status: **initial code-grounded audit; not a repository-wide certification**. This report inspects the production query path, adjacent validators/repair helpers, roadmap and documentation on main. Claims about missing capabilities require additional inspection and integration tests. No live Astra database access or test execution is available in this audit.

## Release priority and observed baseline

The uploaded 49-question Astra live evaluation reports 36 executed, 12 API errors, one other result, and 49 unreviewed semantic verdicts. Nine errors are `semantic_dimension_not_published`. This is a regression gate, not 36 verified correct answers. Restore single-entity behavior before widening semantic capabilities.

## Verified architectural concerns

1. **Single-entity compatibility regression (P0).** `semantic_context.py` interprets `by/per` with a regex and may reject an explicit metric before SQL generation. `prompt_schema_projection.py` reduces prompt-visible physical columns to metric-owner configured attributes, published dimensions, and relationship keys. An existing column absent from semantic attributes (e.g. `managing_owner`) can disappear despite being on the metric's own table. `query_orchestrator.py` also requires a governed metric for aggregate intent. Recommendation: preserve full discovered columns for a provably single-entity route; apply strict published-dimension and relationship rules only when a metric's requested grouping resides on another entity. Keep SQL execution boundaries and published join authorization in both paths.
2. **Orchestrator concentration (P0 maintainability).** `query_orchestrator.py` is ~3,541 lines; `query_correctness.py` is ~2,293 lines. The orchestrator handles intent, metadata, generation, categorical validation/repair, join publication, correctness, retries, execution, and explanation. Extract cohesive responsibilities only after characterization tests. Do not introduce a second query compiler.
3. **Overlapping categorical semantics (P0).** `categorical_intent.py` resolves natural-language categories; `query_orchestrator.py` has `_validate_explicit_categorical_comparison` and `_repair_explicit_categorical_comparison`; `query_correctness.py` contains `_filter_checks` and `_contract_comparison_checks`. Need one typed resolved filter contract, with separate AST validator and repair using that same contract. ASTRA-041 is the regression case; preserve array/UNNEST correctness.
4. **Grouping and ranking interpretation (P0).** `semantic_context.py` regex grouping extraction, `query_orchestrator._required_grouping_columns`, `query_correctness._grouping_checks`, `_explicit_grouping_grain_checks`, `_ranking_grain_checks`, `_comparison_grouping_checks`, `published_grouping_guard.check_published_grouping`, and `ranking_grain_repair` are related but not identical. Define a single resolved grouping/ranking intent, keep independent physical and authorization validators. ASTRA-039 is the regression case.
5. **Join enforcement is intentionally layered (P0).** `published_join_authorization.authorize_exact_selected_route_sql` and `authorize_published_joins` enforce different guarantees; repeated authorization after SQL mutation is safety-critical, **not duplicate business logic**. Keep both, but centralize invocation and trace which grant was used.
6. **Multiple SQL repair paths (P0).** `comparison_group_repair.py`, `ranking_grain_repair.py`, `array_expansion_repair.py`, and orchestrator-local categorical/array repairs modify SQL. Every repaired candidate must rerun the same read-only, scope, join publication, grain, filter and resource-policy checks. Prefer a single repair coordinator that delegates to existing helpers; never run a repair that bypasses checks.
7. **Missing trustworthy acceptance oracle (P0).** The live evaluator separates execution from semantic correctness; 49/49 requires approved expected interpretation and results. Track per-case SQL semantics, expected columns/filters/grouping and approved result assertions. No accuracy claims from SQL execution alone.
8. **Documentation drift (P1).** `README.md` still says 'Current Status: Phase 1 — Foundation' and displays an obsolete minimal project tree despite an operational query orchestrator, UI, governance, evaluation tooling and roadmap. Update docs after the architecture boundaries stabilize.

## Wren architecture parity backlog

These are **target capabilities**, not assertions that Wren has a particular internal implementation or that Data Pilot lacks every component. Evidence states what was directly inspected.

| # | Capability | Priority | Evidence / audit verdict | Next gate |
|---|---|---|---|---|
| 1 | Complete semantic SQL engine | P0 | Current generation uses governed semantic context and LLM SQL; no verified complete deterministic expression compiler in inspected production path. | Typed analytical plan and metric/dimension expression AST; prove SQL equivalent across dialects before routing |
| 2 | Relationship-aware planning | P0 | Semantic context has shortest-path candidates, ambiguity classification; selected-route authorization exists. Successful end-to-end multi-hop route remains unverified per roadmap. | 1-hop and 2-hop positive execution tests; equal-shortest-path ambiguity, stale grant, no-path negative tests |
| 3 | Metric grain and fan-out | P0 | `query_correctness.py` contains relationship and fanout checks, cardinality/key evidence. Coverage of multiple one-to-many paths not established. | 1:N:N synthetic aggregates with expected results and rejection of unsafe measures |
| 4 | Publication-time semantic validation | P0 | Publication metadata exists; full formula/key/path incompatibility validation not established. | Validate formula references, aggregation types, key uniqueness evidence, relationship paths and cycle ambiguity before publish |
| 5 | Complex analytical calculations | P1 | Existing metric expression and aggregate checks; ratios/windows/multi-stage compilation not demonstrated. | Ratio numerator/denominator grains, null/zero policy, window and nested aggregation tests |
| 6 | Calculated semantic fields | P1 | Metric `calculation_expression` is referenced in generator instructions; calculated dimension compiler not verified. | Typed calculated dimension AST, source lineage and safety tests |
| 7 | Views and reusable semantic queries | P1 | Dataset and physical view metadata are not proof of executable composable semantic views. | Inspect view registry, expansion rules, cycle detection and governed composition |
| 8 | Verified query memory | P1 | Evaluation and traces exist; governed approved-example retrieval in production path not verified. | Verified-only examples, datasource/model-version binding, invalidation, no leakage |
| 9 | Value profiling/discovery | P1 | Entity categorical `value_mappings` and retrieval context are visible. Automated profiling quality unverified. | Profiling freshness, confidence, PII-safe sampling and admin approval |
| 10 | Semantic model versioning | P1 | Metadata persistence exists; immutable publish snapshots/rollback not established. | Versioned manifest with atomic publication, lineage, rollback tests |
| 11 | Multi-database support | P2 | Database/SQL provider interfaces exist; verified runtime PostgreSQL-first. | Connector contract suite and per-dialect SQL AST fixtures |
| 12 | Explanation/traceability | P1 | `query_explanation.py` and query trace exist; actual compiled semantic definition IDs not proven end-to-end. | Emit definition IDs, versions, path IDs, filters, repairs and final SQL lineage |
| 13 | Semantic model portability | P2 | Not verified in inspected modules. | Deterministic export/import with validation and diff |
| 14 | Enterprise authorization | P1 | SQL read-only and table/relationship governance present; row/column user authorization and execution identity not verified. | Security threat model, row/column policy and identity propagation tests |
| 15 | Performance optimization | P2 | Resource LIMIT enforcement visible; relationship-aware cost planning/reusable aggregate cache not verified. | EXPLAIN-based diagnostics, plan caps, materialization policy |

## Implementation sequence and non-goals

**Phase 0 (now):** fix the single-entity compatibility regression; characterize ASTRA-003/004/013/015/019/023/026/027/028/031/036/039/041/044/046/049 and all publication failures. Preserve cross-entity authorization. Re-run focused tests and live 49 only after an integrated batch.

**Phase 1 (P0 architecture):** introduce a single *typed semantic intent contract* reusing `SemanticIntentContract` and existing validators, not a second planner. Make route type explicit (single entity versus approved multi-entity), preserve requested filters, measures, grouping, ordering, limit and time. Refactor orchestrator in small behavior-preserving steps; keep validation after every repair.

**Phase 2 (P0 Wren gaps):** publication-time semantic checks, deterministic 1/2-hop relationship route tests, grain/fanout correctness, expression compilation for existing metric definitions.

**Phase 3 (P1):** derived calculations/dimensions, verified examples, semantic model versioning, authorization, semantic lineage; then P2 connectors, portability and optimization.

**Do not:** disable existing validators, silently fallback to same-named physical columns across entities, rewrite the entire orchestrator, equate live SQL execution with semantic correctness, or hardcode Astra-specific production rules.

## Audit scope limits

Inspected: `README.md`, `ROADMAP.md`, `docs/architecture.md`, `semantic_context.py`, `query_orchestrator.py`, `query_correctness.py`, `prompt_schema_projection.py`, `published_grouping_guard.py`, `published_join_authorization.py`, `categorical_intent.py`, `semantic_intent_contract.py`, `comparison_group_repair.py`, `ranking_grain_repair.py`, `array_expansion_repair.py`, `query_explanation.py`, `analytical_evaluation.py`, `time_semantics.py`, plus selected regression tests. Not a complete scan of all routes, metadata persistence, migrations, UI, infrastructure adapters or tests. Full inventory, dependency graph, code duplication measurements and test run remain outstanding.
