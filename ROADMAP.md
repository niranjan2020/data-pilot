# Data Pilot — Product & Architecture Roadmap

> **Single source of truth for development continuity.** Read this file first when resuming in a new chat or development session. Detailed historical investigations belong in Git history, tests, and [the architecture audit](docs/architecture_gap_audit_2026-10-13.md), **not** in this roadmap.
>
> **Status: 2026-10-13.** Items are goals or implementation checkpoints, not claims of verified production completeness.

## 1. Product mission — do not deviate

**Data Pilot is an open-source, self-hostable, LLM-agnostic natural-language-to-SQL product that makes database onboarding quick and lets people ask useful questions with minimal manual configuration.**

Target experience:

1. Connect a supported database.
2. Automatically discover tables, columns, keys, relationships, candidate business concepts, and representative values safely.
3. Select relevant datasets; review or correct only ambiguous/high-impact semantics.
4. Ask questions immediately. Generate safe, accurate SQL; return results, explanations, and diagnostics.
5. Add reusable governed metrics, calculated fields, and relationship definitions **when business meaning requires them**, not as mandatory setup for every simple query.

**Product differentiation:** low-friction onboarding, strong SQL correctness, understandable governance, transparent debugging, open-source usability. Compete with Wren AI on useful capabilities and developer experience, **not** by copying its internals or forcing a full semantic model before the first query.

**Success measure:** a new user can connect a realistic database and answer straightforward single-table questions with little/no configuration; complex questions work once genuinely necessary business semantics are approved. Measure onboarding time, configuration effort, question accuracy, unsupported-question clarity, and regression rate.

## 2. Non-negotiable engineering principles

- **Preserve simple queries.** Discovered columns on a selected single table remain usable for straightforward filters, grouping, sorting, and calculations. Business-specific terms that cannot be inferred safely should trigger clarification or optional configuration, not fabricated SQL.
- **Govern joins, not everything indiscriminately.** Cross-entity metric/dimension queries must use verified relationship paths and authorization. Never substitute a similarly named column on another table or invent a join.
- **One evolving pipeline.** Reuse the existing semantic catalog, `SemanticIntentContract`, relationship resolver, SQL generator, SQLGlot correctness validators, repair helpers, and query orchestrator. Do **not** create a parallel compiler, planner, or second rules engine.
- **Correct results, not just executable SQL.** Preserve requested entity, metric, filter, comparison cohorts, time scope, grouping grain, ranking, and limits. Validate generated and repaired SQL before execution.
- **Minimal configuration with honest limits.** Suggest inferred relationships, values, metrics and formulas; require admin approval only for ambiguous/high-impact definitions or security-sensitive publication. Never invent a business metric when meaning is unclear.
- **Generic across domains.** Astra and AdventureWorks are acceptance datasets, not hardcoded production behavior.
- **Security and privacy.** Read-only SQL, selected-table boundaries, safe execution policies, no storage of customer query-result data by default; future SaaS concerns stay outside the OSS core.
- **Evidence-based delivery.** Separate unit tests, SQL execution, semantic correctness and live acceptance. Never claim 49/49 without independently reviewed expectations/results. Avoid speculative one-off patches and large untested rewrites.

## 3. Current implementation and evidence

Existing code includes database onboarding and discovery, semantic entities/metrics/relationships, metadata persistence, a query orchestrator, LLM-backed SQL generation, SQLGlot validation, governed join authorization, query traces, a UI, Docker setup, and evaluation tooling. **Presence in code does not prove end-to-end completeness.**

**Open release gate — Astra 49 questions:** latest supplied evaluation reported **36 SQL executions succeeded, 12 API errors, 1 other outcome; all 49 semantic verdicts unreviewed**. Some executable SQL is semantically wrong. Historical 49/49 behavior is reported by the user but is not independently established from approved result-level expectations. Regressions appeared after relationship/publication governance changes.

**Known regression classes:** same-table columns hidden by metric prompt projection; overly broad published-dimension rejection; missing filters, wrong grouping/entity/metric, `NULL` aggregates, placeholder SQL; comparison cohort validation including UNNEST; missing-metric responses. Fix by shared root cause, not 49 separate Astra rules.

**Recent change:** single-entity prompt projection compatibility was partially restored and a focused regression test added; broader grouping/metric routing is **not yet fixed or verified**. Do not run the full live batch until the integrated offline regressions are green. Tests and real Astra datasource state require local verification.

## 4. Execution roadmap — ordered by user value

### NOW — R0: Restore baseline and reduce architectural complexity (P0)

**Goal:** simple single-entity questions work again, and adding governed joins cannot break them.

- [ ] Audit complete source tree (API, services, domain, metadata, UI, migrations, tests). Record real duplicates, responsibilities, dead paths and dependency cycles; distinguish required repeated safety checks from duplicate rules. See [audit](docs/architecture_gap_audit_2026-10-13.md).
- [ ] Make query scope explicit: selected single entity vs approved cross-entity path. Single-entity queries retain discovered columns; cross-entity dimension/metric joins require authorized publications and paths.
- [ ] Consolidate *interpretation* of requested metric, grouping, ranking, filters, comparisons and time into the existing semantic intent contract; reuse validators rather than duplicating rules.
- [ ] Correct the live regression classes in coherent batches; retain post-repair SQL safety and join authorization.
- [ ] Run focused + full offline suites; then rerun the **same 49 live questions**, reviewing expected SQL intent and results case by case.
- [ ] Clean obsolete README/project status and maintain concise docs once the code stabilizes.

**Exit:** existing straightforward questions no longer require unnecessary manual semantic publication; approved cross-entity joins remain safe; 49-case evaluation has independently checked verdicts and documented failures (target 49/49, not claimed).

### NEXT — R1: Easy onboarding and trustworthy semantic foundation (P0)

- [ ] Verify one-click-ish database onboarding: connection → schema/key/FK discovery → candidate entities, relationships, value mappings, metrics → selective admin review → query.
- [ ] Validate semantic definitions **at publication time**: referenced columns, formula syntax/type, keys/cardinality, relationship paths, ambiguity, cycles and incompatible definitions.
- [ ] Deterministic 1-hop and multi-hop join planning with unique-path selection, actionable ambiguity, verified join policy and no silent fan-out.
- [ ] Grain-aware aggregation: distinct measures, SUM/AVG on 1:N joins, multi-branch fan-out, pre-aggregation where required, and rejection when correct grain cannot be guaranteed.
- [ ] Extend the **existing** semantic-to-SQL path incrementally for expressions, nested modeled SQL and relationship traversal; no parallel engine.

**Exit:** a new database can be onboarded with minimal configuration, while approved multi-table analytical questions produce independently verified correct results.

### THEN — R2: Functional parity improvements against Wren AI (P1)

- [ ] Complex measures: ratios, derived metrics, distinct measures, windows, multi-stage aggregation and explicit zero/null policies.
- [ ] Calculated semantic dimensions and reusable, composable governed views/queries.
- [ ] Governed query memory: **verified** examples only, scoped to datasource/model version; approval, invalidation and no cross-tenant leakage.
- [ ] Better safe value profiling, categorical synonyms and relationship suggestions, with confidence/freshness and admin review.
- [ ] Immutable published semantic model versions, lineage, rollback and environment-safe change tracking.
- [ ] Explain the actual semantic definitions, join path, filters, SQL repairs and model version used.
- [ ] Row/column authorization and execution identity propagation for enterprise use.

**Exit:** robust complex analytics and explainable, reusable semantics without increasing onboarding friction.

### LATER — R3: Broader reach (P2)

- [ ] Additional database connectors with dialect-specific conformance suites.
- [ ] YAML/JSON semantic model import/export, diff and environment promotion.
- [ ] Cost-aware SQL optimization, diagnostics and reusable aggregations.
- [ ] Improve OSS packaging and developer onboarding; evaluate a separate paid SaaS offering **after** core product value is demonstrated.

## 5. Wren AI capability-gap checklist

Use this as a **functional benchmark**, not an architectural blueprint. `Gap to verify` means coverage has not been proven; it does **not** assert the capability is absent.

| # | Capability | Priority | Data Pilot next proof |
|---|---|---|---|
| 1 | Complete semantic SQL engine | P0 | Modeled expressions, calculated dimensions, nested SQL and relationship traversal compile correctly |
| 2 | Relationship-aware planning | P0 | Deterministic multi-hop routes and ambiguity handling |
| 3 | Metric grain / fan-out protection | P0 | Correct SUM/AVG/distinct on 1:N:N joins |
| 4 | Semantic model validation | P0 | Invalid formulas, keys and relationships blocked at publication |
| 5 | Complex analytical calculations | P1 | Ratios, windows and multi-stage aggregation |
| 6 | Calculated semantic fields | P1 | Governed virtual dimensions and expression expansion |
| 7 | Views / reusable semantic queries | P1 | Executable governed composition and cycle checks |
| 8 | Verified query memory | P1 | Approved examples with scoped retrieval and invalidation |
| 9 | Value profiling / discovery | P1 | Safe categorical values, synonyms, candidate relationships |
| 10 | Semantic model versioning | P1 | Immutable publication, traceability and rollback |
| 11 | Multi-database support | P2 | Real connector/dialect conformance |
| 12 | Query explanation / traceability | P1 | Definition IDs/versions and actual SQL lineage |
| 13 | Semantic model portability | P2 | Validated YAML/JSON import/export |
| 14 | Enterprise authorization | P1 | Row/column policies and execution identity |
| 15 | Performance optimization | P2 | Cost diagnostics and safe aggregate reuse |

## 6. Resume instructions for a new chat or coding session

1. Read **this ROADMAP.md** and [the detailed architecture audit](docs/architecture_gap_audit_2026-10-13.md). Inspect current `main` code and tests; **do not trust old conversation summaries as current implementation truth**.
2. Restate the product goal: **fast onboarding, minimal configuration, accurate NL-to-SQL**. Identify the **first unchecked item in the current phase**; do not jump to unrelated features.
3. Before coding, inspect the existing implementation and its call sites; identify whether the rule already exists. Reuse it. Write regression tests for both **single-table compatibility** and **cross-entity safety**.
4. Make small, cohesive, generic changes. Never hardcode Astra or AdventureWorks semantics, weaken join grants, skip validation after SQL repair, or reset local Docker volumes.
5. Report **exactly** what changed, what tests were actually run, what remains unverified, and the next acceptance step. Never interpret `execution_status=succeeded` as `semantic_correctness=passed`.
6. Update this roadmap **only when phase, verified status, major architectural decision or release gate changes**. Put detailed bugs, commit-by-commit history and long test logs in issues, test artifacts or the architecture audit instead.

**Next engineering action:** finish R0 single-entity grouping/publication compatibility and analytical-intent regressions; verify focused offline tests before another 49-case live run.
