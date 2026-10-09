# Data Pilot Roadmap

## Consolidated offline-to-live evaluation gate — 2026-10-09

- User confirmed **59 focused tests passed** and requested one consolidated offline testing batch before live query testing.
- Added dedicated structural SQL comparison tests and conservative independent SQL semantic expression diagnostics, with cross-domain tests for missing/wrong dimension and metric mappings. These checks deliberately never claim result-level correctness from SQL alone.
- **Remaining unimplemented validation (must not be skipped):** approved categorical values and predicates, full SQL value/parameter matching, joins and fanout/grain, time and snapshot semantics, approved metric physical source, full trusted metadata integration with actual databases, and read-only result comparison. Current AST inspector intentionally rejects some of these SQL shapes. Do not mark them passed or production ready.
- Next: run the combined unit suite once, then use live **dry-run** query testing in the local environment to collect concrete gaps and implement missing capabilities in one coherent follow-up batch before any production routing change.

---


## Legacy query pipeline inspection and offline observation — 2026-10-09

- User confirmed **204 focused tests passed**; full unit suite result not separately reported.
- Inspected `QueryOrchestrator.query(QueryRequest)` and `QueryResponse`. Existing production pipeline produces governed SQL, resolved intent and trace; **it does not emit a typed `AnalyticalPlan`**. Its `dry_run=True` path validates SQL and does not call `execute_query`, but can still access metadata/schema/LLM services.
- Added `observe_legacy_query_dry_run` for opt-in operator use with a trusted orchestrator. It always forces dry-run, does not save history, rejects completed responses or execution results, and returns a diagnostic observation explicitly marked **typed_plan_available=False**. Added **14 tests**, awaiting local verification.
- **Not yet connected to the scored golden runner:** SQL-only legacy observations are deliberately not converted into fake typed-plan success. Next implement an independent typed-plan extraction/evidence contract or a SQL AST-to-operation evaluator with explicit provenance, after confirming production metadata and dialect behavior. No changes to live query routing.

---


## Opt-in offline golden prediction runner — 2026-10-09

- User confirmed **185 focused tests passed**; full unit suite result not separately reported.
- Added `run_offline_golden_evaluation`: loads persisted datasource-scoped semantic grants, skips blocked cases, and **only when explicitly enabled** calls a supplied async prediction adapter; independently evaluated evidence is scored using the existing batch report. Missing prediction is not evaluated; adapter failures are failed without exposing exception details. Added **19 regression scenarios**, awaiting user verification.
- **Integration boundary:** no concrete live NL-to-SQL prediction adapter has yet been wired; no LLM/SQL is called by the runner itself. Adapter must produce genuinely evaluated `AnalyticalEvaluationResult` evidence, never self-asserted success. This does not measure actual question accuracy until wired to real predictions and independently reviewed gold expectations.
- Next: inspect actual query pipeline interfaces, implement a non-executing prediction adapter only where the pipeline supports it, validate real published catalog against gold fixtures, and add result-level evaluation later. Do not alter live request routing.

---


## Evidence-aware golden batch reporting — 2026-10-09

- User confirmed **150 focused tests passed**; full unit suite result not separately reported.
- Added pure batch scorer with distinct **passed / failed / blocked / not evaluated** dispositions. It requires complete readiness evidence, unique case IDs and consistent prediction results; missing or blocked questions cannot inflate evaluated accuracy. Added **35 tests**, awaiting local execution.
- The scorer consumes independent evaluation results and persisted-publication readiness; it does **not** generate plans, call an LLM, execute SQL, inspect the user's local databases, or establish result-level correctness.
- Next: connect predictions to real question-to-plan pipeline in an opt-in offline evaluator, validate the illustrative golden references against the actual published catalogs, then add safe read-only query-result comparisons. No live query routing changes.

---


## Trusted golden evaluation metadata integration — 2026-10-09

- User confirmed **127 focused readiness tests passed** (full unit suite result not separately reported).
- Added `evaluate_published_golden_readiness`: read-only asynchronous integration of the existing persisted metric/time publication loader and per-attribute publication loader. Checks a batch of golden cases against one datasource-scoped metadata snapshot; fails closed on missing stores, unknown datasource, ambiguous/unpublished semantics and unsupported capabilities. Added **23 integration test cases** across two illustrative domains, awaiting local verification.
- This does not authorize SQL execution or integrate into live NL-to-SQL. It does not verify metric physical source, category mappings, joins, time/snapshot grain, or expected query results.
- Next: run focused and full tests, then inspect actual published Astra/AdventureWorks metadata and build prediction-to-gold and read-only result comparisons.

---


## Published semantic catalog readiness — 2026-10-09

- User confirmed **103 focused golden-question and evaluation tests passed**; full unit suite result not separately reported.
- Added read-only `validate_golden_catalog_readiness` that accepts a **trusted, datasource-scoped** `PublishedSemanticContext` and separately published `AnalyticalDimension` attributes; rejects missing/ambiguous dimensions or metrics, physical dimension source mismatch, cross-datasource context, and pending capabilities. Added **24 tests**, awaiting local verification.
- This is a pure metadata acceptance gate; it does not retrieve records itself, grant permissions, resolve category labels, verify physical metric sources, execute queries, or integrate with live NL-to-SQL. Actual production callers must load metadata through persisted publication stores and still validate physical bindings, tenant isolation, eligibility, joins and execution authorization.
- Next: connect trusted loaders to evaluation orchestration and inspect real Astra/AdventureWorks published metadata, then correct golden specifications and build read-only result-level evaluations.

---


## Golden analytical question catalog — 2026-10-09

- User confirmed **120 focused analytical evaluation and SQL tests passed**; full unit suite not separately confirmed.
- Added generic capability-aware golden catalog contracts and coverage reporting; 16 illustrative questions split evenly across Astra and AdventureWorks, with 10 **supported plan shapes only** and 6 explicitly pending advanced capabilities.
- Added 71 parametrized catalog validation scenarios, awaiting local test execution. Questions are illustrative specifications; **not** validated against the actual published schema, metrics, category mappings, LLM predictions, or query results. Do not interpret supported shape as production-ready business-question support.
- Next: connect evaluation to real published semantic catalog and NL-to-plan predictions; independently review and correct golden expectations (e.g. multi-table product attributes, ownership labels, snapshots) before datasource-level acceptance; then run read-only result comparisons under policy. Keep live routing unchanged.

---


## Analytical evaluation harness checkpoint — 2026-10-09

- User confirmed **88 focused analytical SQL tests passed** (full unit suite not separately confirmed).
- Added generic `AnalyticalEvaluationCase`, `AnalyticalEvaluationResult`, and `evaluate_analytical_case`: compares typed operation sequence, bound semantic dimension/metric names, ordered parameters, expected physical source, and governed SQL verifier status. Pure offline evaluation: no LLM, database access, or execution authorization.
- Added **32 evaluation tests** across Sales and Astra-style fixtures: 8 supported shapes, 10 semantic mismatches, 6 SQL/parameter tampering cases, 8 invalid contract checks. Awaiting local test verification.
- This is an **evaluation readiness harness**, not full Stage 5. Ground-truth question-to-plan prediction, query execution results, categorical value resolution, grain/snapshot semantics, and governance Admin integration remain future gates. No live routing changed.
- Next: run tests; then extend to datasource-grounded gold cases and result-level checks after safe evaluation access is available.

---


## Cross-domain analytical correctness batch — 2026-10-09

- User confirmed **56 focused analytical verification tests passed**. Full unit suite was not separately reported.
- Added **32 cross-domain regression scenarios** (20 aggregate/direction combinations, 6 filter-order/parameter combinations, 6 invalid-limit checks), awaiting user execution. Improved AST verifier fail-closed handling for malformed role/binding lookups.
- This is still **Stage 4 verification plus pre-evaluation contract coverage**, not completion of Stage 5 live evaluation. Real Astra/AdventureWorks question-to-result correctness, governed eligibility, snapshot/grain behavior, and Admin publication permissions remain open.
- Next: run focused + full suite, repair failures, then prepare realistic datasource-grounded question/SQL/result evaluation fixtures. Preserve existing live routing and local datasource state.

---


## Analytical verification batch — 2026-10-09

- User verified **20 focused SQL verification tests** after fixing parameter test fixture tuples. Full unit suite result not independently reported.
- Batch implementation (awaiting user verification): independent AST parameter-position markers for WHERE EQ/IN and HAVING; a **36-case** cross-domain verification matrix covering Sales and vessel sources, supported filter/threshold combinations, five aggregate/sort/limit variants, bound injection/unicode inputs, SQL tampering, and governance bounds.
- Batch development cadence: prefer coherent feature + 20–50 case regression batches; reserve substantial time for actual Astra/AdventureWorks evaluation and debugging.
- **Stage 4 remains OPEN**: deterministic recompilation plus AST-role checks do not prove arbitrary SQL semantic equivalence, relationship fanout, dataset eligibility, or authorization.
- Next acceptance: run focused tests and full unit suite, fix any regressions, then test cross-domain governed semantics and trusted publication/admin integration. Do not force-route live NL-to-SQL or reset datasource metadata.

---


## Analytical SQL AST verification checkpoint — 2026-10-09

- User confirmed 15/15 deterministic SQL verification tests and 9/9 unified compiler dispatch tests; full unit-suite result was not separately reported.
- Added SQLGlot AST structural gate to the deterministic plan-to-SQL verifier: single SELECT, exactly one approved physical table, grouping, ordering, limit, two projections, and rejection of JOIN/subquery/set operations/window/CTE. **Awaiting user test verification.**
- This is **not yet independent semantic equivalence verification**: expected SQL still comes from the same deterministic compiler. AST shape checks are an additional defense, not proof of filter/metric/grain equivalence.
- Roadmap next: expand AST verification against independently constructed plan expectations (predicate fields/operators, aggregate functions, grouping and sort identity, parameter positions), cross-domain negative tests, trusted Admin attribute publication and permissions integration, then Astra/AdventureWorks live evaluation.
- Do not force-route live traffic, reset local datasource metadata, or treat green unit tests as end-to-end acceptance.

---


## Analytical planning checkpoint — 2026-10-09 (user-verified 1,175 unit tests)

**Roadmap alignment:** Generic composable plan and basic governed binding contracts exist; deterministic SQL compilation, plan/SQL verification and live Astra/AdventureWorks evaluation remain OPEN. Top-N remains one acceptance scenario, not a separate query engine.

**Governance work in progress:** Persistent publication store for metrics/time roles, datasource-scoped metadata loader, administrative workflow contracts and entity-attribute dimension extraction have unit coverage. These are not yet integrated into the authenticated Admin API or live NL-to-SQL execution path. No full end-to-end publication acceptance has been demonstrated.

**Contract correction (this increment):** Entity approval is not permission to group by every attribute. Add a separate datasource + entity ID + attribute name publication store. Legacy `dimension` grants still refer to entities and MUST NOT be treated as attribute approval. Do not activate dimension binding until the loader consumes explicit attribute grants. Attribute renames, revocation and authorization require integration tests.

**Next priority:** Wire approved attributes into the metadata loader and plan binder; connect trusted Admin permissions; then proceed with deterministic SQL compilation and AST verification. Preserve C2/C3 acceptance, C4/C5 governance backlog, and C7 visualization as a separate milestone. No Docker volume resets or automatic publication.

---


## Generic governed analytical planning — architecture direction (2026-10-09)

**Top-N is a test case, not a dedicated product capability.** Do not add special-case operator, TEU, or Top-N SQL routing. Preserve existing generic query correctness and user-approved semantic metadata.

- Represent analytical intent as a composable plan: typed operations (filter, aggregate, group, sort, limit, rank, compare, threshold, contribution, time-window), with explicit inputs, outputs, dependencies and execution order.
- Bind each operation to published semantic entities, dimensions, metrics, grain, relationships, eligibility predicates and time roles. Keep datasource-specific policies in metadata, never in generic code.
- Resolve ambiguous scope (global vs partitioned ranking), cohort vs output metric, and unspecified measures through semantic defaults or clarification; do not silently invent policy.
- Compile validated plans to dialect-aware SQL. Validate the **plan and resulting SQL AST**, including operation order, cohort selection, grouping grain, metric definitions, filters, limits, and fan-out protection.
- Make ranking-policy contracts reusable *inputs* to the general plan, not the center of the engine. Do not expose unpublished policies or treat any limit as a ranking operation.
- Roll out incrementally: (1) generic plan model and cross-domain tests; (2) governed binding and planner integration; (3) deterministic SQL compilation; (4) plan-to-SQL verification; (5) live Astra and AdventureWorks evaluation.
- Maintain backward compatibility with existing NL-to-SQL requests; no forced routing to an incomplete planner. Avoid altering local datasource configurations or resetting metadata.

---


> Living roadmap for the Data Pilot open-source core and future SaaS product.
>
> **Rule:** update this file whenever a milestone is completed, reprioritized, or a benchmark exposes a new reliability gap. Benchmark evidence, not feature speculation, drives Stage A.

**Last updated:** 2026-10-08  
**Current focus:** Core OSS — Stage C3: AI provider and datasource onboarding refinement (C2 acceptance passed)  
**Current semantic evaluation baseline:** 39/39 passed (100.0%) through the live production pipeline after B4 dialect isolation (p50 2.986 s, p95 4.249 s).  
**Current unit regression baseline:** **1004 passed** (user-verified 2026-10-09, before C4 categorical proposal regressions). Full integration/evaluation suite and live semantic benchmark are not verified by this count.

## Visualization Intelligence — generic result presentation (planned, 2026-10-09)

**Priority:** separate Stage C7 enhancement, after active semantic-to-SQL category correctness and governed ranking work. **Status: roadmap only; not implemented.** Do not modify current SQL correctness behavior as part of visualization delivery.

- **Shape-aware chart selection:** choose chart types from typed result roles (dimensions, measures, time), cardinality and user intent; support single-category bars, two-category grouped bars, time-series lines, and suitable multi-measure comparisons. Fall back to a table when no trustworthy chart fits.
- **Generic pivoting:** convert two categorical dimensions plus one measure into category-by-series grouped bars; preserve original result rows, nulls, labels, and metric values. Support stacked bars only when composition/additivity makes sense; cap series/cardinality and provide scroll or alternate layout.
- **Semantic labels:** use published dimension/category display labels for legends and tooltips while retaining underlying codes for query correctness; never hardcode ownership, operator, vessel, or AdventureWorks names.
- **Narrative correctness:** describe category comparisons as comparisons, never period changes without a time dimension; avoid misleading repeated labels or arithmetic on unrelated rows. Validate comparisons, denominators, units, and metric grain against returned data.
- **Acceptance:** fixtures across unrelated domains; category-by-series pivot accuracy, missing categories/nulls, high cardinality, semantic labels, chart fallback, and deterministic narrative tests. Chart improvements must not alter generated SQL, query safety, or published semantics.

## Governed Top-N ranking — metric and dimension UX (planned, 2026-10-09)

- Define reusable ranking policies in Admin Studio, discoverable from the **Metrics** section but stored as governed ranking metadata, not as a fake `Top N` metric.
- Policy fields: applicable entity/dimension, ranking metric, sort direction, default N or maximum N, eligibility/filter scope, global versus per-group partitioning, tie policy, approval/publication state. User-specified N may override defaults within policy bounds.
- Example datasource-specific policy: rank operators by approved SUM(TEU capacity) over an explicitly governed eligible fleet, then count ON ORDER vessels by selected operator and segment. Verify grain and avoid duplicate capacity. Never assume vessel count is the ranking metric.
- Planner should distinguish `top N operators overall, broken down by segment` from `top N operators within each segment`; clarify when ambiguous. Generate safe two-stage SQL, then validate ranking metric, partitioning, eligibility, N and final grouping.
- Keep domain-specific defaults only in datasource semantic configuration; add cross-domain regression fixtures (customers/revenue, products/units, operators/capacity).

---

## Governed Top-N operator ranking — design checkpoint (2026-10-09)

- Astra-specific approved default: an unqualified **top N operators** means operators ranked by descending **SUM of TEU capacity**, not vessel count. This is datasource semantic configuration, not a global Data Pilot assumption.
- Query example: "on order vessel count for top 10 operators in each segment". First select 10 operators using the approved TEU ranking metric and its defined fleet eligibility/scope, then count distinct vessels with status ON ORDER grouped by operator **and** vessel_segment. Never collapse operator cohorts or rank by the requested output count unless the user explicitly requests it.
- Clarify semantics for "top N in each segment" versus "top N globally, broken down by segment"; require a defined scope or ask a clarification if ambiguous. Preserve operator identity in result and grouped comparison chart.
- Implementation pending: semantic metadata for governed ranking defaults (entity, dimension, metric, aggregation, eligibility, scope, tie policy), planner support for two-stage ranking with CTE/window functions, AST checks for ranking metric and partitioning, and evaluation cases. Avoid hardcoding TEU or maritime logic in generic services.
- Verify the actual TEU capacity physical column and any per-vessel duplication/grain before defining SUM; ranking must not double-count duplicated vessel records.

---

## C4 bounded categorical proposals — provider increment (2026-10-09)

- Added an explicitly invoked PostgreSQL categorical proposal method: quoted identifiers, read-only transaction, statement timeout <=5s, capped distinct values <=100, fail closed for high cardinality (no partial enum published).
- Three unit regressions added; **awaiting user verification**. No automatic scanning, API exposure, semantic publication, or runtime synonym resolution yet.
- Follow-up: add a governed admin-only proposal endpoint with dataset/column allowlist, bounded per-request cost, and review/edit/publish UX. Do not run against all discovered tables.
- User confirmed 1004 unit tests before this increment; Astra configuration and Docker volumes must remain intact.

## C4 catalog restoration checkpoint (2026-10-09)

- User verified `astra-dev` saved connection and existing Vessel semantic entity restored after C4 catalog query regression fix (`56a4cc6`). No metadata reset or volume deletion.
- Fixed catalog query to return discovered unique constraints and columns as distinct fields; added two regression tests for the four-field response and empty uniqueness evidence (`11bdebe`).
- Latest user unit result: 1002 passed **before** the two new regressions. Awaiting rerun. C4 remains open: next bounded, opt-in categorical proposals and admin review.

## C4 schema discovery — first increment (2026-10-08)

- Added `UniqueConstraintMetadata` to the physical `TableMetadata` discovery contract (constraint name, ordered columns, PK flag), backward-compatible default empty list.
- PostgreSQL introspection now reads validated `pg_constraint` PK/UNIQUE constraints, preserving composite column order.
- Added two unit regressions for round-trip composite uniqueness and legacy catalog payloads.
- **Awaiting user verification:** unit suite and live Astra schema rediscovery. No claims of test success yet.
- **Not yet implemented:** UNIQUE indexes without constraints, partial/expression index analysis, candidate value discovery, bounded distinct-value sampling, review/publish UX, persistence of unique evidence across all catalog snapshots, or enforcement in SQL validation.
- Next C4 increment: determine existing schema snapshot serialization paths and expose reviewed constraint evidence; then bounded, opt-in categorical value proposals. Do not execute unbounded `SELECT DISTINCT` across all 292 discovered tables.

---

## 2026-10-08 C3 credential-management acceptance

- User verified **998 unit tests passed** after adding three saved-datasource login regression tests (invalid login, successful replacement, secret-write rollback).
- User tested a deliberately invalid username/password against saved `astra-dev`; validation was rejected. Immediately afterward, **Test saved connection** returned **Saved datasource connection successful**, confirming the old login still works.
- Saved datasource details and the username/password update UI are visible; credentials are not displayed in read APIs.
- Password-only rotation and combined username/password update are implemented. **C3 credential negative-path acceptance passed**; successful real-world username migration has not been exercised, and username/secret persistence across two stores is not crash-atomic. Do not claim full production-grade atomicity.
- **Next primary work:** C4 discovery review (PK/FK/UNIQUE metadata and bounded categorical value proposals), followed by C5 human-approved semantic publication. Prioritize generic features; preserve approved Astra configuration and keep historical snapshot views independent of current-state filters.
- **C5 release blockers remain:** mandatory `source_active = TRUE` dataset policy enforcement, current-versus-history routing, relationship authorization hardening, and approved value mapping enforcement. These are backlog, not completed capabilities.

---

## 2026-10-08 roadmap audit and delivery priorities

**Primary active milestone: C2 — one-command local deployment.** C1 is complete. C2–C8 remain open until their individual exit criteria are demonstrated; a green unit suite does not establish that Docker startup, onboarding, or first-answer time targets work on a clean machine.

**Verified checkpoints**
- Latest user-executed unit suite: **995 passed** (2026-10-08, before subsequent metadata/UI fixes; rerun required).
- Last recorded live semantic evaluation: **39/39 passed**, after B4; **not rerun** at the 976-test checkpoint.
- Stage A and documented B1–B4 milestones remain complete as recorded below. Preserve existing B5/B6 status where documented; do not infer completion from test growth.
- C1 onboarding contract and persisted state: complete. C2 deployment: active; clean-machine exit gate not yet demonstrated.

**Recent correctness hardening — implemented, not a release gate substitute**
- Governed join graph, grouping, time grain, aggregation placement, and conservative fan-out diagnostics.
- Derived join-key uniqueness, join connectivity, join-type classification, right-hand derived uniqueness evidence, and cardinality evidence summaries.
- Explicit physical unique-key *metadata* validation with negative/adversarial regression coverage.
- These diagnostics do **not** prove end-to-end metric-row preservation, automatically inspect database UNIQUE constraints, or waive `join_fanout_violation`. A declared `*_unique_key_verified` flag must only be supplied by trusted catalog evidence; it is not proof merely because an API caller supplied it.

**2026-10-08 C5 relationship-governance audit (parallel implementation, NOT C5 completion)**
- Implemented persisted relationship review, verification evidence, publication/revocation, current-publication retrieval, SQL AST join-policy checks, and HTTP orchestrator wiring for trusted publication authorization.
- User-confirmed regression: **976 unit tests passed** at `4d011a5`. Earlier PostgreSQL publication integration suite: **2 passed**; rerun after the latest runtime wiring remains pending.
- **Security/behavior gaps before claiming runtime enforcement complete:** reject any physical SQL JOIN with no required relationship contract when publication governance is configured; prove datasource-scoped authorization; eliminate the second publication lookup and ensure correctness checks consume exactly the grants validated at the boundary; test permitted joins, denied/unpublished/revoked/stale joins, extra joins, wrong keys/types, dry runs and correction/recovery paths.
- **Potential migration issue:** older semantic relationship records without review/evidence fields retain legacy correctness behavior; determine the explicit migration and fail-closed policy for production joins.
- **Test gap:** add orchestrator and API integration regressions exercising the actual composition root, not just isolated publication helpers.
- **C5 broader scope remains OPEN:** provider-independent AI semantic suggestions for entities/attributes/metrics/time dimensions/business rules, review/edit/reject UX, persisted approvals, and complete onboarding journey have not been demonstrated.
- **Priority guardrail:** finish this bounded authorization hardening, then return to the primary C2 clean-install gate and C3–C5 user-facing onboarding. Do not equate growing unit counts with installation or live benchmark success.

**C5 backlog — governed dataset filters and current-versus-history semantics (2026-10-08)**

- Add a typed, persisted **mandatory dataset filter** contract (column, operator, typed value, applicability, approval state) to the semantic catalog; do not rely on free-text `query_constraints` or LLM instructions as enforcement.
- First acceptance fixture: `astra.vessels` is a current-state table; `source_active = TRUE` must apply to every query using that dataset, including counts, groupings, and joins. This is a **generic configurable policy**, never a hardcoded vessel rule.
- Historical/trend analysis uses a **separate snapshot view** already maintained by the Astra team. Discover and govern that view independently; do not blindly apply the current-state `source_active` filter to historical snapshots.
- Enforce mandatory filters in generated SQL and at the deterministic AST/execution boundary, including aliases, subqueries, joins, and dry runs. Fail closed if the filter is missing or can be bypassed.
- Define explicit administrator-approved applicability/exceptions and clarify whether a question refers to current state or historical trend. Do not infer exemptions from wording alone.
- Add negative and positive regression/evaluation cases for current versus historical questions, missing/wrong filters, join placement, and accidental leakage of inactive rows.
- **Dependency:** complete C2 clean-install gate first; schedule this alongside C4–C5 discovery and semantic approval. Value discovery/canonical value resolution remain C4–C5 backlog as well.
- **Status:** requirements recorded; runtime enforcement NOT implemented.

**C2 full isolated onboarding and restart acceptance — PASS (user-verified 2026-10-08)**

- Fresh project `datapilot-c2-clean` on port 3001: first-run welcome; Gemini provider validated; PostgreSQL connection tested/saved; 292 tables discovered across 15 schemas; `astra.fixtures` and `astra.vessels` selected; both semantic dataset definitions approved; Finish semantic review transitioned to Admin Studio.
- Relationship `astra.fixtures.vessel_id → astra.vessels.id` passed cardinality/reference verification. Join-policy publication remains gated; not a C2 requirement.
- After restarting all four containers, `GET /api/setup/readiness` returned HTTP 200 with `ready=true`, `setup_ready=true`, and metadata storage, AI provider and datasource all `ready`.
- C2 deployment and first-run onboarding acceptance satisfied; follow-on first governed query, broader UX and relationship publication are separate work. Keep the isolated project and original volumes intact.

**C3 datasource UX refinement — implemented, awaiting build verification (2026-10-08)**

- Admin Studio now keeps saved datasource identity separate from the editable new-connection test form; no longer copies the saved datasource name into fields alongside localhost/postgres defaults.
- Clarifies that the connection form tests another connection and that saved onboarding credentials are managed separately.
- C2 restart readiness was verified as true after full-container restart; browser refresh persistence should still be checked.
- UI build and regression verification are pending.

**C2 isolated fresh-install bootstrap — PASS (user-verified 2026-10-08)**

- Using Compose project `datapilot-c2-clean` with isolated PostgreSQL, Qdrant and secrets volumes, all four services built and became healthy.
- `http://localhost:3001/health` returned HTTP 200, status ok.
- `http://localhost:3001/api/setup/readiness` returned HTTP 200 with `ready=false`, `setup_ready=false`, `metadata_storage=ready`, `ai_provider=not_ready`, `data_source=not_ready` as expected.
- Browser displayed **Welcome to Data Pilot**, first-run provider configuration and blocked subsequent onboarding steps.
- **Still open:** validate AI provider, datasource, discovery/selection, semantic review and first governed query on the isolated installation; verify persisted setup after restart. Do not mark C2 complete prematurely.
- Keep primary `infra` Compose volumes intact.

**C2 existing-install smoke test — PASS (user-verified 2026-10-08)**

- `docker compose -f infra/compose.yaml up --build -d --wait`: all four services healthy (PostgreSQL, Qdrant, API, web).
- Through nginx at localhost:3000: `/health` → HTTP 200 status ok; `/health/ready` → HTTP 200 status healthy with metadata reachable; `/api/setup/readiness` → HTTP 200, `ready=true`, `setup_ready=true`, metadata/AI provider/datasource all ready.
- Unit-test summary was not included in the pasted output; do not claim a new passing count.
- This validates an **existing-volume installation**, not clean-machine/empty-volume bootstrap. C2 remains open until fresh-install, first-run onboarding, and persistence checks pass. Never erase the user's existing volumes for testing.

**Next C2 acceptance checkpoint — local stack smoke test**

- User has confirmed the Astra semantic datasets API responds after catalog-initialization deadlock mitigation; this is **not** evidence of a clean-install pass.
- On the current Windows installation, verify Compose service health and HTTP liveness/readiness separately; collect response status and JSON for `/health/ready` and `/api/setup/readiness`.
- Confirm existing persisted semantic configuration survives `docker compose up --build -d --wait` (without removing volumes).
- Record any failing container healthchecks, startup/migration errors, and API/UI routing errors before attempting C3.
- A successful existing-install smoke test is an intermediate C2 checkpoint; fresh-volume clean-install and first-run Welcome screen remain exit gates.

**Priority order (avoid indefinite correctness-only iteration)**
1. **C2 now:** verify Compose startup, dependency health, migrations, first-run Welcome screen, and actionable startup errors on a clean supported machine. Record the actual command and observed outcomes.
2. **C3–C4:** usable model-provider/target-Postgres connection wizard and automatic schema/constraint discovery with reviewable table selection.
3. **C5–C7:** human-approved semantic bootstrap, Admin/Data Readiness, and trustworthy Ask experience.
4. **C8:** clean-machine Windows/macOS/Linux validation, TTFA measurement, sample data, and onboarding resilience.
5. **Parallel bounded correctness track:** connect *trusted discovered* PK/UNIQUE metadata to governed joins; test safe and unsafe multi-join cardinality with execution-backed fixtures; retain fail-closed behavior until proven. Avoid treating added unit-test count as proof of correctness.
6. **Stage D and SaaS:** unchanged release and customer-demand gates; SaaS remains deferred.

**Next validation commands:** `python -m pytest tests/unit -q` for unit regression, plus the existing evaluation harness and a documented clean Docker Compose run. Record each separately; do not conflate unit tests with live pipeline or installation success.

---

# 1. Core Open-Source Engine

## Product objective

Build a self-hostable, governed NL-to-SQL engine that converts natural-language analytical questions into safe, semantically correct SQL. The LLM may interpret language and generate candidate SQL, but deterministic semantic metadata and correctness checks remain the authority for execution.

Target flow:

```text
Question
  -> Semantic retrieval / governed context
  -> Ambiguity and clarification
  -> Deterministic time interpretation
  -> SQL generation
  -> AST / safety validation
  -> Governed correctness validation
  -> Resource policy
  -> Database execution
  -> Structured result presentation / summary
```

## Completed

### Foundation and architecture
- Modular/hexagonal Python architecture with FastAPI composition.
- Domain interfaces separating database, metadata, semantic retrieval, LLM, SQL generation, and validation.
- PostgreSQL database provider and metadata catalog.
- Gemini LLM adapter behind provider abstractions.
- Qdrant semantic retrieval.
- SQLGlot AST validation and read-only query safety.
- Unit, integration, and evaluation test structure.
- Open-source-first separation: no SaaS tenancy/billing concerns in the core.

### Physical and semantic metadata
- Physical schema discovery for tables, columns, and relationships.
- Persisted semantic catalog.
- Governed datasets, entities, relationships, metrics, attributes/business metadata.
- Semantic context assembly with physical metadata.
- Semantic retrieval/context budgeting.
- Synonym-driven semantic discovery.

### Query orchestration and ambiguity
- Production query orchestrator.
- Entity ambiguity clarification and resume.
- Metric ambiguity clarification and resume.
- Attribute ambiguity clarification and resume.
- Value-only filter ambiguity using governed attributes.
- Multiple explicit metric composition.
- Follow-up semantic inheritance.
- Explicit follow-up override.
- Prior SQL is not reused as semantic truth for follow-ups.

### Deterministic time semantics
- Relative time interpretation.
- Last/this month, quarter, and year.
- Year-to-date.
- Last N days/months.
- Daily/weekly/monthly/quarterly/yearly grouping.
- Trend defaults.
- Month-over-month and year-over-year comparison planning.
- Governed time-column selection.
- Deterministic half-open time ranges.

### Deterministic SQL correctness
Implemented pre-execution checks for:
- Governed physical table scope.
- Governed derived metric expression and aggregation.
- Required grouping dimensions.
- Governed filters.
- Governed relationship/join paths.
- Aggregation grain / one-to-many fan-out protection.
- Governed time column and range.
- Governed time grouping grain.
- Comparison time envelopes.

Runtime normalization also handles SQL quoting, aliases, schema-qualified table identity, and quoted/unquoted governed metric identifiers.

### Result intelligence
- Deterministic result-shape classification.
- KPI/scalar, comparison, ranking, trend, categorical, and table presentation paths.
- Deterministic analytical summaries/diagnostics such as leaders, percentage change, concentration, trend movement, and related result insights.

### Evaluation foundation
- Existing `tests/evaluation` framework retained as the single evaluation system.
- Semantic evaluation cases exercise the production query pipeline.
- Structured clarification evaluation.
- Evaluation summary and latency percentiles.
- Required/forbidden deterministic correctness-code assertions.
- No duplicate benchmark architecture and no LLM-as-judge dependency.

---

## Building now — Stage A: Finish NL-to-SQL correctness and evaluation

### Goal
Make analytical correctness measurable and use benchmark failures to decide what production behavior to improve.

### Working loop
```text
Benchmark
  -> classify failure by layer
  -> fix the real production defect
  -> add regression test
  -> rerun benchmark
  -> record new baseline
```

### Current checkpoint — 2026-10-06

Evaluation V2 progression:
- Initial run: **0/20**. Canonical SQL table/identifier differences caused systemic false correctness failures.
- After physical-scope and metric-expression canonicalization: **10/20 (50%)**.
- After governed grouping/filter requirement propagation: **17/20 (85%)**.
- After metric-aware ranking/grouping resolution: **19/20 (95%)**.
- After composed entity + attribute grouping resolution: **20/20 (100%)**.
- Latest semantic latency: **p50 3.270 s**, **p95 4.644 s**.
- Targeted orchestrator/correctness suite reached **50/50 passing** before the final composed-grouping regression test was added.

A1 defects fixed without weakening benchmark expectations:
- Propagated governed grouping and filter requirements into the shared generation/correctness plan.
- Canonicalized quoted/aliased physical table identities and metric identifiers.
- Added clarification precedence for selected grouping attributes.
- Distinguished metric ranking (for example, customers by order count) from dimensional grouping.
- Resolved composed governed phrases such as entity + attribute (for example, product + colour).
- Preserved deterministic correctness validation as the execution authority.

### Stage A work remaining

#### A1. Correctness propagation — COMPLETE
- Production 20-case semantic benchmark: **20/20 (100%)**.
- All previously observed grouping/filter propagation defects have regression coverage.
- Do not weaken these expectations as evaluation coverage grows.

#### A2. Evaluation coverage expansion — COMPLETE
First expansion checkpoint:
- Semantic suite expanded from **20 to 25 cases** without production feature changes.
- **Second expansion checkpoint: 30/30 semantic cases passed (100.0%) with 52/52 targeted correctness/orchestrator unit tests passing.**
- **Third expansion checkpoint: 35/35 live semantic cases passed (100.0%); targeted orchestrator/fixture/ambiguity suite is 29/29.**
- **Fourth expansion checkpoint: 39/39 live semantic cases passed (100.0%), including real multi-turn follow-up conversations through the production pipeline.**
- **A2 exit checkpoint: 86/86 targeted correctness/orchestrator/evaluation tests and 39/39 live semantic cases passed after the adversarial and multi-dimension changes. A2 is complete; additional cases should now be driven by identified product risks rather than an arbitrary case-count target.**
- Added versioned production-shaped semantic metadata for generic Customer/Product/Order evaluation, exercised through the real `SemanticContextAssembler` rather than benchmark-only semantic logic.
- Added and validated multi-dimension grouping across attributes on one entity and across independent entities. This exposed and fixed two production gaps: later dimensions after conjunctions were dropped, and global phrase-specificity could incorrectly discard an independent explicit entity.
- Added adversarial correctness coverage for partial multi-dimension grouping, incomplete cross-entity relationship paths, and plausible-but-wrong join columns.
- Confirmed governed correctness fails closed at the orchestrator boundary: semantically invalid SQL is rejected before policy enforcement/database execution.
- Added high-composition coverage for multi-metric output, ranking, governed filters, synonyms, attribute grouping, and relationship traversal.
- Added a versioned generic `SemanticCatalog` fixture so ambiguity/negative evaluation can be reproduced without relying on local AdventureWorks metadata state.
- Added deterministic fail-closed behavior for questions that cannot map to any governed entity when a semantic catalog is populated; these queries are rejected before SQL generation, validation, or database execution.

- The 26–30 slice added composed multi-metric ranking, governed filters, entity/metric synonyms, and relationship traversal.
- This slice exposed and fixed metric-vocabulary leakage into grouping resolution: entity terms embedded inside governed metric phrases (for example an entity synonym occurring inside a metric name) no longer become accidental grouping dimensions.
- Evaluation diagnostics now support focused `--case` execution and include SQL/correctness context on result-row policy failures.
- Result: **25/25 passed (100.0%)**.
- Latency: **p50 3.139 s**, **p95 3.946 s**.
- Added coverage for entity/metric synonyms, non-default ranking limits, synonym + filter composition, metric-ranked entity synonyms, and governed attribute grouping.
- An initially underspecified non-aggregate "items by colour" case was replaced with the analytically explicit "units sold by product colour"; benchmark expectations must represent unambiguous correctness requirements.

Expand from the current semantic set toward roughly 50–75 meaningful cases covering:
- Basic semantic resolution.
- Metrics and metric synonyms.
- Dimensions and multi-dimension grouping.
- Governed filters and values.
- Multiple metrics.
- Governed joins.
- Fan-out-safe and fan-out-unsafe scenarios.
- Time filtering.
- Time grouping/grain.
- Comparisons.
- Ambiguity/clarification.
- Follow-up questions.
- Negative/adversarial correctness cases.
- Unsupported/unanswerable questions.

Prefer semantic assertions and correctness trace codes over exact SQL-string comparison.

#### A3. Time benchmark integration — COMPLETE
- Versioned representative governed time-dimension metadata using the generic commerce fixture.
- Covered deterministic last month, YTD, last N days, monthly/quarterly grouping, rolling 12 months, grouping-only, MoM, and YoY semantics.
- Bridged resolved governed time plans into deterministic SQL correctness and evaluation-harness scoring.
- Asserted `time_filter_alignment`, `time_grain_alignment`, and comparison-period correctness.
- Added `time_comparison_alignment` / `time_comparison_violation` so comparison SQL must preserve each governed period rather than only the outer envelope.
- Covered wrong-column, wrong-boundary, wrong-grain, envelope-only comparison, and orchestrator fail-closed paths.
- A3 regression checkpoint: **108/108 passed** across time semantics, correctness, orchestrator, evaluation harness, and versioned semantic metadata tests.

#### A4. Failure taxonomy and reporting — COMPLETE
- Added a stable structured failure taxonomy covering semantic retrieval, semantic resolution, ambiguity/clarification, time interpretation, SQL generation, AST/safety validation, governed correctness, execution, and result correctness.
- Evaluation assertions assign failure categories at the point of failure rather than parsing human-readable error messages afterward.
- Added explicit `SemanticRetrievalError` and `TimeInterpretationError` orchestrator boundaries so runtime failures can be attributed without guessing.
- Runtime classification distinguishes SQL generation/LLM failures, validation failures, governed-correctness failures, database execution failures, semantic metadata/resolution failures, retrieval failures, and time-interpretation failures.
- Unknown runtime exceptions remain intentionally unclassified instead of being assigned to a misleading stage.
- Benchmark reporting now includes category-level affected-case counts and pass rates alongside overall accuracy and latency.
- Added regressions proving retrieval and time failures stop before downstream SQL generation/execution.
- A4 full regression checkpoint: **127/127 passed**.
- Live production-pipeline semantic benchmark: **39/39 passed**.

#### A5. Stage A exit criteria — COMPLETE
- Core correctness and evaluation suites are green.
- Final comprehensive Stage A regression checkpoint: **133/133 passed**.
- Latest verified live production-pipeline semantic benchmark baseline: **39/39 passed**.
- Machine-checkable coverage gates preserve broad semantic composition, clarification, unsupported-question, follow-up, governed-time, join, and fan-out coverage.
- Unsupported and ambiguous questions fail safely before SQL execution; clarification resume and stale/invalid selections are regression-covered.
- Required governed correctness fails closed when verification is unavailable rather than treating unknown as safe.
- The A5 audit closed an unrelated-subquery fan-out bypass.
- Failure taxonomy/reporting isolates semantic retrieval/resolution, clarification, time interpretation, SQL generation, validation, governed correctness, execution, and result correctness.
- Known limitation carried deliberately into Stage B: complex subquery/pre-aggregation fan-out analysis can report `fanout_verification_unavailable`; it is not falsely reported as aligned.
- Stage A is complete with a stable measured baseline suitable for the robustness phase.

Do **not** weaken expectations to preserve a headline benchmark score. Correctness and explainability remain the priority.

---

## Stage B: Robustness and query-engine hardening — historical milestones / ongoing safety maintenance

Stage A is complete. Stage B hardens recovery, provider isolation, resource safety, and diagnostics without weakening deterministic correctness.

### B1. Bounded SQL correction/retry — COMPLETE
- Exactly one correction attempt is allowed for deterministic recoverable governed-correctness violations.
- Correction receives the original governed context, failed SQL, and structured correctness feedback.
- Corrected SQL is rebound and must pass the complete safety validation, governed correctness, and execution-policy pipeline again.
- Safety/policy failures, unverifiable correctness, and unknown correctness failures remain terminal.
- Correction attempts are captured in the query trace for diagnostics and explainability.
- Focused B1 regression: **49/49 passed**.
- Full Stage A + B1 regression: **151/151 passed**.
- Live production-pipeline semantic benchmark: **39/39 passed**.

### B2. Bounded execution-error recovery — COMPLETE
- Deterministically classifies structured database execution failures into recoverable versus terminal categories and fails closed when provider evidence is missing or unknown.
- PostgreSQL execution failures expose normalized, structured provider diagnostics including SQLSTATE without parsing opaque exception messages.
- Exactly one execution-recovery generation is allowed for eligible SQL execution failures.
- Recovered SQL is rebound and must pass the complete safety, governed-correctness, and resource-policy pipeline before execution.
- Connection, authorization, privilege, timeout/cancellation, resource, provider-runtime, unknown, and unstructured failures remain terminal.
- B1 governed-correctness correction and B2 execution recovery have explicit ownership boundaries: B1 may be followed by one independent B2 recovery, but B2 failures cannot re-enter B1 or B2.
- Execution recovery is recorded separately in QueryTrace for explainability and diagnostics.
- Final focused/full automated regression: **101/101 passed**.
- Final live production-pipeline semantic benchmark: **39/39 passed (100.0%)**.
- One preceding benchmark run produced 38/39 solely because Gemini returned a provider ConnectError during SQL generation; rerunning the unchanged code produced 39/39, so no correctness expectation was weakened.

### B3. Explicit unsupported-question handling — COMPLETE
- Added structured rejection codes for unsupported questions and invalid explicit entity, metric, attribute, and time-dimension selections.
- Preserved governed ambiguity as clarification while unsupported/out-of-governance questions are deterministically rejected.
- Invalid explicit selections take precedence over generic unsupported detection.
- Unsupported questions fail closed before SQL generation/execution; evaluation can require rejected responses to contain no SQL.
- Adversarial coverage proves irrelevant high-similarity retrieval cannot authorize an unsupported question against the authoritative semantic catalog.
- Shared exact governed entity terms remain ambiguous rather than being silently selected.
- B3 focused hardening regression: **89/89 passed**.
- Full automated regression after B3: **316/316 passed**.
- Final live production-pipeline semantic benchmark: **39/39 passed (100.0%)**, latency **p50 3.157 s / p95 4.258 s**.
- A preceding live run was blocked by a Gemini async transport ConnectError; direct REST and synchronous Gemini calls succeeded, and the unchanged benchmark subsequently returned 39/39. No correctness expectation was weakened.

### B4. Stronger dialect isolation — COMPLETE
Keep PostgreSQL first-class while preventing PostgreSQL-specific behavior from leaking into provider-independent query-engine contracts.

#### B4.1. Dialect-isolation architecture audit — COMPLETE
The audit found that the public ports are already mostly dialect-aware: `DatabaseProvider.dialect`, `SQLGenerator.generate(..., dialect=...)`, `SQLValidator.validate(..., dialect=...)`, and `SchemaMetadata.dialect` carry the target dialect through the main workflow. SQLGlot validation and identifier binding also already translate canonical Data Pilot dialect names through `infrastructure/sql/dialects.py`.

The main isolation gaps are:
1. **Governed correctness is hard-coded to PostgreSQL.** `application/services/query_correctness.py` parses and canonicalizes SQL with SQLGlot's `postgres` dialect instead of receiving the active database dialect. This is the highest-priority leak because deterministic correctness is part of the provider-independent application pipeline.
2. **Execution recovery is PostgreSQL SQLSTATE policy in the application layer.** `application/services/execution_recovery.py` contains PostgreSQL-specific SQLSTATE codes/classes. Recovery classification needs provider/dialect-owned evidence or policy rather than pretending those codes are universal.
3. **Identifier binding has PostgreSQL semantics in a generic SQL module.** The implementation correctly solves PostgreSQL case-folding/quoted-identifier behavior, but its contract/name currently suggests generic behavior. It should become an explicit dialect-aware binding strategy before another provider is added.
4. **The orchestrator imports concrete SQL infrastructure behavior.** `QueryOrchestrator` directly calls `bind_physical_identifiers`; dialect-specific SQL normalization should enter through a port/strategy so the application layer does not choose infrastructure behavior.
5. **PostgreSQL adapter internals are legitimate provider-specific code.** psycopg, `information_schema`/PostgreSQL catalog queries, read-only transactions, `statement_timeout`, and normalized PostgreSQL diagnostics belong in `infrastructure/database/postgresql.py` and should remain there.
6. **PostgreSQL metadata persistence is platform infrastructure, not target-query dialect leakage.** The metadata/semantic catalog can remain PostgreSQL-backed while target databases eventually use other dialects.
7. **Composition is intentionally PostgreSQL-only today.** The API composition root constructs `PostgreSQLDatabaseProvider`; this is acceptable while PostgreSQL is the only registered target provider, but provider selection should eventually be registry/factory based rather than spread into the core.
8. **Default dialect values are PostgreSQL-biased but not yet harmful.** `SchemaMetadata.dialect` defaults to `postgresql` and `sqlglot_dialect(None)` defaults to `postgres`. Preserve compatibility now; require explicit dialect at execution/correctness boundaries as isolation improves.

B4 implementation order from this audit:
- **B4.2:** thread the active dialect into deterministic governed correctness and remove hard-coded PostgreSQL parsing/canonicalization.
- **B4.3:** introduce a dialect-aware SQL binding/normalization boundary and remove the orchestrator's direct dependency on the concrete identifier-binding function.
- **B4.4:** make execution-error recovery classification provider-aware without weakening B2 fail-closed semantics.
- **B4.5:** add dialect-boundary regressions and close B4; do not add a second database provider merely to prove the abstraction.

#### B4.2. Governed correctness dialect isolation — IMPLEMENTED
- The active target database dialect is now threaded from the database provider into deterministic governed correctness.
- SQLGlot parsing and expression/table canonicalization use the shared dialect mapper rather than hard-coded PostgreSQL.
- PostgreSQL remains the compatibility default for direct callers, while production orchestration supplies the provider dialect explicitly.
- Focused B4.2 regression checkpoint: **90/90 passed**, including non-PostgreSQL syntax coverage.

#### B4.3. SQL binding/normalization boundary — IMPLEMENTED
- Added a provider-independent `SQLIdentifierBinder` port and a dialect-aware SQLGlot adapter.
- `QueryOrchestrator` no longer imports the concrete physical identifier-binding function.
- Initial generation, B1 correction, and B2 recovery all pass through the same injected binding boundary.
- API and live-evaluation composition explicitly install the SQLGlot binder.
- Focused B4.3 regression checkpoint: **107/107 passed**.

#### B4.4. Provider-aware execution recovery — IMPLEMENTED
- PostgreSQL SQLSTATE interpretation moved out of the application layer and into the PostgreSQL database adapter.
- Providers expose normalized `ExecutionRecoveryEvidence`; the application recovery gate consumes that evidence without interpreting vendor codes.
- Missing/unknown provider classification remains terminal, preserving B2 fail-closed behavior and the single bounded recovery attempt.
- Focused B4.4 regression checkpoint: **104/104 passed**.

#### B4.5. Dialect/provider boundary regression gate — COMPLETE
- Added architecture regressions that prevent hard-coded PostgreSQL SQLGlot dialects from returning to governed correctness.
- The gate prevents the orchestrator from regaining a direct dependency on the concrete identifier-binding function.
- The gate prevents PostgreSQL SQLSTATE tables from leaking back into the application recovery policy and verifies that PostgreSQL owns its recovery codes.
- B4 final automated regression: **331/331 passed**.
- B4 final live production-pipeline semantic benchmark: **39/39 passed (100.0%)**, latency **p50 2.986 s / p95 4.249 s**.
- No benchmark expectation was weakened and no second database provider was added merely to prove the abstraction.
- **B4 exit criteria are satisfied.**

### B5. Query timeout and resource-policy hardening — COMPLETE
Protect connected databases and the Data Pilot process from expensive or unexpectedly large generated queries without changing governed analytical semantics.

#### B5.1. Resource-policy architecture audit — COMPLETE
The existing engine already has a useful first layer:
- `QueryExecutionPolicy` defines timeout, maximum result rows, SQL length, and LIMIT controls.
- `SQLQueryPolicyEnforcer` parses the validated SQL AST, adds a default LIMIT to non-aggregate queries, and caps oversized literal LIMIT values.
- Policy enforcement occurs after safety/governed-correctness validation and before every execution, including B1/B2 regenerated SQL through the shared execution path.
- The orchestrator passes `timeout_seconds` explicitly to the database provider.
- PostgreSQL applies transaction-local `statement_timeout` and executes on a read-only connection.
- The orchestrator also rejects a returned result whose `row_count` exceeds `max_result_rows`.

Hardening gaps identified:
1. **Result-row protection is partly post-execution.** Aggregate/grouped queries are exempt from automatic LIMIT injection, so a high-cardinality GROUP BY can still return an excessive result set and consume transfer/memory before the post-execution row-count check rejects it.
2. **Non-literal LIMIT values are not fail-closed.** A LIMIT expression/parameter that cannot be deterministically evaluated is currently left unchanged rather than rejected or safely bounded.
3. **Policy invariants are not validated as a coherent contract.** `default_limit`, `max_limit`, and `max_result_rows` can be configured inconsistently.
4. **Timeout configuration is split between provider default and execution policy.** Runtime execution correctly receives the policy timeout, but composition/configuration should establish one explicit effective query timeout and regression-test it.
5. **Timeout/cancellation must remain terminal.** PostgreSQL SQLSTATE `57014` is already terminal in B2; B5 must preserve that and must never regenerate/retry a query merely because it exceeded its resource budget.
6. **Current trace records policy SQL/warnings and execution timing, but not the effective resource budget.** Diagnostics should make the applied timeout/row/limit budget visible.
7. **SQL length is bounded, but query-shape cost is intentionally not estimated yet.** Do not introduce unreliable heuristic cost scoring or EXPLAIN-based autonomous decisions in this milestone.

#### B5.2. Deterministic row/limit policy — COMPLETE
- Row-producing queries are bounded before execution, including grouped aggregates, DISTINCT queries, and set operations.
- Scalar aggregates remain unmodified when they are provably single-row.
- Non-literal/dynamic LIMIT expressions fail closed rather than bypassing deterministic row controls.
- Explicit and injected limits respect the coherent result-row budget.

#### B5.3. Coherent effective resource budget — COMPLETE
- Query execution policy validates `default_limit <= max_limit <= max_result_rows` at configuration time.
- Query timeout configuration must be positive.
- `QueryTrace.resource_budget` records the effective timeout, row, SQL-length, and LIMIT controls applied to the query.

#### B5.4. Timeout/recovery regression gate — COMPLETE
- PostgreSQL cancellation/timeout SQLSTATE `57014` remains terminal and cannot trigger B2 regeneration/retry.
- Normal execution, B1 correction, and B2 recovery all re-enter the same resource-policy boundary before execution.
- Focused B5 regression checkpoint: **129/129 passed**.
- B5 final automated regression: **351 passed, 2 skipped**.
- B5 final live production-pipeline semantic benchmark: **39/39 passed (100.0%)**.
- No live benchmark expectation was weakened.
- **B5 exit criteria are satisfied.**

### B6. Diagnostic traces and explainability — COMPLETE
Make query decisions inspectable without exposing model chain-of-thought or duplicating orchestration logic.

#### B6.1. Explainability architecture audit — COMPLETE
Existing trace coverage is already substantial:
- retrieval candidates include selected/rejected governance decisions and reasons;
- governed datasets, entities, relationships, metrics, rules, and time dimensions are recorded;
- physical tables/columns, resolved parameters, clarification selections, follow-up context, time interpretation, and context-budget diagnostics are recorded;
- generated, identifier-bound, validated, and policy SQL are recorded;
- deterministic correctness checks, B1 correction attempts, B2 execution-recovery attempts, resource budget, and execution timing/row count are recorded;
- exact LLM messages are retained for admin diagnostics.

Gaps identified:
1. **Trace data is diagnostic but not organized as an explanation contract.** Consumers must understand internal fields and reconstruct the decision path themselves.
2. **No deterministic stage/outcome timeline exists.** There is no compact representation of which stages were reached, passed, clarified, rejected, corrected, recovered, skipped, or executed.
3. **Ambiguous/rejected outcomes have useful structured response data, but the trace does not summarize why processing stopped.**
4. **Raised validation/execution failures can carry details through exceptions, but they do not produce the same complete explanation shape as successful responses.** Do not redesign API error handling until the explanation contract is stable.
5. **Raw LLM messages are admin-only diagnostics, not user explainability.** User-facing explanations must be derived from governed/deterministic evidence and must never expose hidden reasoning or imply that model prose is correctness authority.
6. **SQL lineage exists as separate fields but lacks explicit transformation labels.** Consumers should be able to distinguish generated -> bound -> validated -> policy SQL and B1/B2 proposals without guessing.
7. **Explainability should be derived from the existing trace/response rather than maintained as a second orchestration state machine.**

B6 implementation order:
- **B6.2 — COMPLETE:** introduced a provider-independent deterministic explanation model/builder derived from `QueryResponse` + `QueryTrace`, covering outcome, governed interpretation, SQL lineage, checks, resource policy, recovery, and execution.
- **B6.3 — COMPLETE:** exposed the deterministic explanation on completed, dry-run, ambiguous, and rejected responses through a single response-boundary derivation path.
- **B6.4 — COMPLETE:** regression coverage now protects normal, clarification, rejection, B1, B2, dry-run, and resource-policy explanation paths.

B6 closure evidence:
- Focused B6 regression gate: **90/90 passed**.
- Full automated suite: **358 passed, 2 skipped**.
- Unchanged live semantic benchmark: **39/39 passed (100.0%)**.
- Live latency at closure: **p50 2954 ms, p95 4178 ms**.
- Benchmark expectations were not weakened.

### B7. Regression corpus growth from real OSS usage — CURRENT
Turn realistic usage patterns and discovered failures into durable regression assets without hard-coding AdventureWorks or customer-specific semantics into the core.

B7 implementation order:
- **B7.1 — COMPLETE:** audited the current evaluation/regression corpus, fixtures, benchmark case schema, and failure-capture boundaries.
  - The live semantic corpus is 39 configured-source cases in `tests/evaluation/semantic_cases.json`; it is intentionally source-specific evaluation data, not core product logic.
  - A separate generic deterministic fixture already exists under `tests/fixtures/postgresql` with the smaller provider-independent `tests/evaluation/cases.json` corpus.
  - `EvaluationExpectation` already models semantic selection/exclusion, status, clarification, SQL presence/fragments, governed-correctness codes, and optional result ground truth.
  - Runtime failures are classified by pipeline stage and summaries retain category rates plus latency percentiles.
  - The runner directly composes normal adapters, so the live gate does not duplicate orchestration logic.
  - Audit found one contract-loading gap: `rejection_code` and `require_no_sql` existed in the evaluator but were not loaded from JSON by the live runner. This was fixed with a loader regression.
  - Current gap for B7.2: cases are evaluation-oriented but do not yet carry provenance/reproduction metadata needed to promote real OSS incidents into a durable, reviewable regression corpus.
- **B7.2:** define a provider/domain-neutral regression-case contract for promoting reproducible real-world failures into deterministic tests.
- **B7.3 — COMPLETE:** strengthened durable regression coverage across semantic ambiguity/rejection, governed correctness, SQL resource policy, B1 correction, B2 recovery, dry-run behavior, and deterministic explainability. Coverage remains split intentionally: domain-neutral deterministic fixtures/unit regressions protect engine behavior, while the configured-source 39-case live corpus protects end-to-end semantic quality without moving AdventureWorks semantics into core code.
- **B7.4 — COMPLETE:** documented the OSS regression-contribution workflow and review checklist, including reproduction-first promotion, sanitization, correct test-layer selection, provenance/reproduction metadata, deterministic expectations, and explicit prohibition on weakening expectations to make failures pass. Closure gates passed: focused B7 regression gate **141/141**, full automated suite **362 passed / 2 skipped**, and unchanged live semantic benchmark **39/39 passed (100%)**.

### B7 / Stage B closure

**B7 is COMPLETE. Stage B — Production-grade query engine is COMPLETE.**

Final B7 validation:
- Focused regression gate: **141/141 passed**.
- Full automated suite: **362 passed, 2 skipped**.
- Live configured-source semantic benchmark: **39/39 passed (100%)**.
- The live benchmark expectations remained unchanged.
- Regression provenance/reproduction metadata remains evaluator-only and does not influence runtime orchestration or SQL generation.
- Real OSS failures now have a documented, sanitization-first path into durable deterministic regression coverage.

The next roadmap phase is **Stage C — Open-source product experience**.

Remaining:
- Regression corpus growth from real OSS usage (B7 current).

Avoid autonomous/unbounded agent loops.

---

## Independent review closure

**Independent review hardening is COMPLETE.**

Closure validation:
- Confirmed review defects were fixed without weakening deterministic governance or live benchmark expectations.
- Final automated suite after review hardening: **372 passed**.
- Focused orchestrator regression gate after schema-backed governed filter repair: **62/62 passed**.
- Final configured-source live semantic benchmark: **39/39 passed (100%)**.
- AdventureWorks/domain-specific `Color` hard-coding was not restored; value-only categorical filter inference now falls back to authoritative physical schema column types when persisted semantic attributes do not carry type metadata.
- Remaining review observations concerning application/infrastructure composition, admin resource lifetime, dynamic data-source/provider configuration, readiness checks, query-history result privacy, and stronger evaluation result ground truth are intentionally carried into Stage C architecture/product work rather than patched as Stage B behavior.

**Stage A COMPLETE. Stage B COMPLETE. Independent review COMPLETE. Stage C is now ACTIVE.**

---

## Next — Stage C: Open-source product experience

Stage C is the **face of Data Pilot**. The production-grade engine from Stage B is valuable only if a new OSS user can experience it without understanding Data Pilot internals, editing configuration files, manually provisioning infrastructure, or reading architecture documentation first.

### Stage C north star

**Clean machine -> connected database -> first trustworthy governed answer in <= 5 minutes.**

Non-negotiable product metrics:
- **Time to First Answer (TTFA): <= 5 minutes** for the supported happy path.
- **Manual configuration files required before first answer: 0.**
- A technically competent user unfamiliar with Data Pilot should reach a successful query without reading architecture documentation.
- Onboarding quality is a product capability, not just documentation.

### Product positioning

Competitors such as Wren AI and Vanna AI are useful onboarding-friction benchmarks. Data Pilot should not differentiate merely by having a UI or Docker packaging. For every setup step a comparable product exposes, ask: **can Data Pilot safely remove or automate this step?**

The user's conceptual model should be:

```text
Data Pilot
    |
    v
Your Database
```

PostgreSQL metadata storage, Qdrant, migrations, indexing, internal service URLs, model adapters, and other implementation details should remain behind the product experience wherever possible.

### Core experience principles

1. **Zero configuration files for first-time users.**
   - No mandatory `.env`, YAML, JSON, semantic files, Qdrant configuration, or Python edits before the first answer.
   - Advanced configuration may remain available later, but the UI owns first-run setup.

2. **Connect -> Discover -> Review -> Ask.**
   - Keep onboarding short and explicit.
   - Target wizard: **Connection -> Data -> Business Context -> Ready**.
   - Always show setup progress and actionable status.

3. **Automatic semantic bootstrap, with human approval.**
   - Use discovered schemas, tables/views, columns, types, PK/FK/constraints, and safe metadata to suggest entities, attributes, relationships, metrics, time dimensions, and business terminology.
   - AI/model output is a suggestion, never silent governance authority.
   - Users can **Approve / Edit / Reject** suggestions.
   - Approved semantic configuration becomes authoritative for the deterministic governed engine.
   - Do not reintroduce the removed saved-query/template approach.

4. **Progressive governance instead of configure-everything-first.**
   - Let users obtain value from a small approved starting model.
   - When a later question exposes missing business meaning, ask for the smallest clarification/configuration needed.
   - Example: if "active customer" is undefined, present candidate definitions or allow a custom rule; once approved, persist the governed definition for future questions.

5. **Visible Data Readiness.**
   - Provide a readiness view covering connection, schema discovery, relationships, entities, metrics, time dimensions, and business rules.
   - Surface unresolved ambiguity such as competing revenue definitions, missing relationships, or multiple candidate time dimensions.
   - Explain why certain questions may not yet be answerable reliably.

6. **Errors become actions, not stack traces.**
   - Connection failures should identify whether network, authentication, database, permissions, or schema access failed.
   - Internal Qdrant/indexing/platform failures should be translated into user-facing states with retry/remediation actions.
   - Do not expose infrastructure exceptions as the normal onboarding UX.

7. **Bring-your-own-model-provider configuration.**
   - Gemini remains the currently implemented provider, but Stage C must not make Gemini a product-level requirement.
   - Users should be able to configure their own supported provider credentials through the UI, beginning with a clean provider abstraction and expanding adapters incrementally.
   - Planned provider choices include **Gemini / Google AI, OpenAI, Anthropic Claude, and Azure OpenAI**; additional providers can be added behind the same contract when justified.
   - Provider setup UX: choose provider -> enter API key/endpoint where applicable -> choose/validate model -> **Test** -> ready.
   - Secrets must never be written to semantic configuration, query traces, normal logs, or committed configuration files.
   - Do not hard-code provider-specific model names into the core orchestration layer.
   - Supporting multiple providers does **not** mean all providers must be implemented at once; preserve a stable provider boundary and add adapters with focused compatibility tests.

### Target first-five-minute journey

```text
1. Start Data Pilot
2. Welcome / first-run screen
3. Configure AI provider using user's own key
4. Connect PostgreSQL and test connection
5. Discover schemas/tables/relationships automatically
6. Select a recommended/small starting table set
7. Review and approve semantic suggestions
8. Index/bootstrap automatically
9. Land in Ask Data Pilot with suggested questions
10. Receive first governed answer with result + explanation + optional SQL
```

No manual creation of Data Pilot's internal PostgreSQL database, Qdrant collections, migrations, embeddings, or service URLs should be required on the supported local path.

### C1 — First-run product architecture and UX contract

Define onboarding as a stable product workflow before allowing frontend screens to invent orchestration rules.

Deliverables:
- First-run detection.
- Setup-state/state-machine contract.
- Onboarding/status API.
- System readiness API.
- Configuration persistence boundary.
- Setup progress and resumability after restart/failure.
- Provider-independent AI configuration contract.
- Secret-handling boundary.
- Explicit TTFA instrumentation points.
- Screen-by-screen first-five-minute UX specification.

Exit criteria:
- Backend exposes enough deterministic state for the UI to render every onboarding step without guessing.
- Setup can resume safely after an interrupted step.
- Provider credentials are never returned through normal read APIs or logs.
- No runtime query-engine behavior is duplicated in the UI.

#### C1 implementation checkpoint — COMPLETE (2026-10-07)
- Deterministic persisted setup state covers AI provider, target data source, data selection, semantic review, and ready.
- Setup/status and product-readiness APIs derive UI state from persisted facts rather than browser state or environment-variable presence.
- Runtime health is separated from product onboarding readiness and uses a provider-independent health boundary.
- PostgreSQL metadata readiness is live-probed; Windows uses the psycopg-compatible selector event-loop policy.
- AI configuration is provider-independent for Gemini, OpenAI, Anthropic, and Azure OpenAI; Gemini has the first concrete validation adapter and additional provider implementations remain incremental Stage C work.
- Provider credentials cross a separate secret boundary and normal read APIs expose only credential presence.
- Reconfiguration invalidates prior provider readiness before replacement validation.
- Restart/resume regressions prove the current onboarding step is recomputed from persisted facts.
- The first-five-minute screen contract and explicit TTFA milestone contract are documented in `docs/stage-c-first-five-minute-ux.md`.
- Validation checkpoint: focused C1 suites green and full automated suite **400/400 passed** after Windows/runtime-health hardening.

C1 exit audit:
- Deterministic UI state: **met**.
- Interrupted/restarted setup resumption: **met**.
- Credential non-return boundary: **met**.
- Query-engine logic remains backend-owned: **met by contract/architecture**.
- TTFA instrumentation points: **defined**; concrete milestone recording lands with the corresponding C2-C7 actions so C1 does not invent timings for operations that do not exist yet.

**C1 COMPLETE. C2 ACTIVE.**

### C2 — One-command local deployment

Target happy path:

```text
git clone ...
docker compose up
```

The local stack may internally include:
- Data Pilot Web.
- Data Pilot API.
- Platform PostgreSQL.
- Qdrant.

But startup must automatically handle:
- health/dependency ordering;
- platform database initialization;
- migrations;
- Qdrant collection/index initialization;
- internal service discovery/default URLs;
- first-run detection.

Exit criteria:
- A clean supported machine reaches the Welcome screen with one documented startup command.
- Users do not manually provision internal Postgres/Qdrant resources.
- Startup failures produce actionable health information.

### C3 — AI provider + PostgreSQL connection wizard

#### AI provider
Initial UX supports bring-your-own credentials:
- Gemini / Google AI.
- OpenAI.
- Anthropic Claude.
- Azure OpenAI.

Implementation may land incrementally; the UI/provider contract must not assume Gemini.

Provider diagnostics:
- credentials accepted/rejected;
- endpoint/deployment validation where applicable;
- selected model availability/compatibility;
- safe test request;
- actionable quota/rate-limit/authentication feedback.

#### Target database
PostgreSQL remains the first supported target database for Stage C. Do not dilute onboarding quality by adding many database providers at once.

Connection wizard:
- host;
- port;
- database;
- username;
- password;
- SSL/options where needed;
- **Test Connection**.

Diagnostics should distinguish:
- network reachability;
- authentication;
- database selection;
- permissions;
- schema visibility.

Credentials/secrets must not leak into traces/logs/semantic metadata.

### C4 — Automatic schema discovery and data selection

After a successful target connection:
- discover schemas, tables, views, columns, data types, PKs, FKs, and deterministic relationship metadata;
- present a searchable/selectable schema browser;
- recommend a small starting set rather than blindly onboarding hundreds of tables;
- support re-scan/refresh when schema changes;
- make large-schema progress visible.

Example UX:
```text
247 tables discovered.
Recommended starting set: 12.
[Review tables]
```

Exit criteria:
- User can understand what Data Pilot will govern/index before continuing.
- Large databases do not force an all-or-nothing first run.

### C5 — AI-assisted semantic bootstrap

This is a strategic Stage C capability.

From discovered metadata, propose:
- entities;
- attributes;
- relationships;
- metrics;
- time dimensions;
- business terminology/rules where evidence is sufficient.

Every model-generated item is visibly **Suggested by Data Pilot** until approved.

Admin actions:
- Approve.
- Edit.
- Reject.

Principles:
- LLM/provider helps create candidate configuration.
- Deterministic approved configuration remains query-time authority.
- Suggestions must carry enough evidence/source mapping for review.
- Ambiguous definitions must be surfaced rather than guessed.
- Semantic bootstrap must work with any supported AI provider through the provider abstraction.

### C6 — Admin Studio and Data Readiness

Provide the long-term configuration surface rather than forcing users back to files.

Proposed navigation:
```text
Overview
Data Sources
Schema

Semantic Model
  Entities
  Relationships
  Metrics
  Time Dimensions
  Business Rules

AI Settings
Query Playground
Evaluation
System
```

Data Readiness should show:
- connection health;
- schema state;
- confirmed/unconfirmed relationships;
- semantic coverage;
- metric/business-rule coverage;
- unresolved ambiguity;
- indexing state;
- issues requiring action.

The UI should explain why a question may be unreliable or unsupported rather than presenting semantic setup as opaque configuration.

### C7 — Production-quality Ask Data Pilot experience

Keep the normal-user surface simple.

Core response experience:
- natural-language question;
- concise answer/summary where supported;
- result table;
- appropriate chart/visualization;
- deterministic **Why this answer** section;
- governed metric/entity/time/rule evidence;
- optional **View SQL**;
- clarification UI when semantics are ambiguous;
- clear rejection/unsupported-question UX;
- visible correction/recovery outcome where useful without exposing hidden chain-of-thought.

Reuse the deterministic B6 explanation contract. Do not create a second explanation system in the frontend.

Suggested starter questions should be generated from the approved semantic model, not hard-coded domain examples.

### C8 — Onboarding resilience, guided demo, and clean-machine validation

Treat onboarding as an engineering quality gate.

Test at minimum:
- fresh Windows;
- fresh macOS;
- fresh Linux;
- empty/small/large target databases;
- wrong database password;
- insufficient permissions;
- unreachable target database;
- Qdrant/platform database unavailable;
- invalid/expired AI key;
- unsupported/unavailable model;
- AI quota/rate-limit failure;
- schema with no foreign keys;
- schema with hundreds of tables;
- interrupted/restarted onboarding.

Measure:
- installation/startup time;
- time to provider readiness;
- time to database connection;
- schema discovery duration;
- semantic bootstrap duration;
- **Time to First Answer**;
- setup failure/recovery rate.

Also provide:
- a reproducible sample database;
- guided demo path;
- concise quickstart;
- screenshots/GIF/video showing **Connect -> Discover -> Review -> Ask -> Explain**.

### README / GitHub first impression

The README should lead with user value and a short quickstart before architecture detail.

Target shape:
```text
DATA PILOT

Ask your database questions.
Governed SQL. Your data stays with you.

Get started:
git clone ...
docker compose up

Open the local Data Pilot UI.

1. Configure your AI provider
2. Connect PostgreSQL
3. Select your data
4. Review Data Pilot suggestions
5. Ask your first question

Target: <= 5 minutes
```

Architecture, correctness internals, and contributor details remain available below the first-run path rather than blocking it.

### Stage C implementation order

- **C1:** First-run/onboarding architecture + UX contract.
- **C2:** One-command Docker Compose local installation.
- **C3:** Bring-your-own AI provider configuration + PostgreSQL connection wizard/diagnostics.
- **C4:** Automatic schema discovery + table selection.
- **C5:** AI-assisted semantic bootstrap + human approval.
- **C6:** Admin Studio + Data Readiness.
- **C7:** Production-quality Ask Data Pilot experience.
- **C8:** Onboarding resilience, sample DB, docs, and clean-machine testing.

### Stage C exit gate

Stage C is complete only when:
1. A new user can start Data Pilot with the documented one-command local path.
2. No manual configuration-file editing is required before the first answer.
3. User can configure their own supported AI provider credentials through the product.
4. User can connect PostgreSQL, discover/select data, review semantic suggestions, and ask a governed question through the UI.
5. The first answer includes understandable result/explanation behavior and ambiguity is handled interactively rather than guessed.
6. Happy-path **TTFA is <= 5 minutes** on the reference setup.
7. Onboarding failures are actionable and resumable.
8. Stage B correctness/safety/recovery regressions remain green.
9. The unchanged live semantic benchmark remains a release gate where relevant.

### Explicitly out of Stage C scope

Do not turn Stage C into SaaS or infrastructure expansion. Defer:
- multi-tenancy;
- billing/subscriptions;
- organizations and enterprise RBAC;
- Kubernetes/cloud control plane;
- many target database providers at once;
- autonomous/unbounded agents;
- dashboard-builder complexity;
- broad MCP/plugin ecosystem;
- enterprise SSO/SCIM/private networking.

Stage C has one mission: **make the production-grade governed engine we already built exceptionally easy to experience.**

---

## Next — Stage D: OSS release hardening

Planned:
- Clean Docker Compose installation.
- Reproducible sample environment.
- CI quality gates.
- Supported Python/runtime matrix.
- Security documentation.
- Contributor/developer documentation.
- Architecture and README refresh.
- Versioning/changelog/release process.
- OSS alpha release (target label: v0.1 when quality criteria are met).
- Optional telemetry only if explicitly opt-in.

---

## Explicitly deferred from the Core roadmap

Until justified by Stage A/B evidence:
- Large multi-agent architecture.
- LLM-as-judge as a correctness authority.
- Automatic prompt tuning.
- Many database providers at once.
- Production Kubernetes architecture.
- SaaS tenancy/billing/auth concerns inside the OSS core.
- Customer-data persistence that is not necessary for the product.

---

# 2. SaaS Layer — Later

The SaaS layer is intentionally deferred until the OSS core demonstrates reliable analytical value and obtains useful external feedback.

## SaaS principles
- Keep commercial SaaS concerns outside the reusable core.
- Reuse the same governed query engine rather than fork its behavior.
- Design for tenant isolation and cost control from the start when SaaS work begins.
- Avoid storing customer query data or database data unless required and explicitly designed.
- Treat security, auditability, and operational reliability as product requirements rather than add-ons.

## Candidate SaaS capabilities

### Platform
- Multi-tenancy and tenant isolation.
- Authentication and authorization.
- Organizations/workspaces/users/roles.
- Tenant-specific data-source connections and semantic configuration.
- Secrets management.

### Commercial
- Plans and entitlements.
- Usage metering.
- Query/token/model cost accounting.
- Billing/payment integration.
- Free/trial limits.
- Upgrade/downgrade/cancellation flows.

### Operations
- Production cloud deployment.
- 99.9% availability target when commercially justified.
- Logging, metrics, tracing, alerting.
- Audit logs.
- Backups/disaster recovery.
- Rate limits and abuse protection.
- Support/admin tooling.

### Enterprise — only when demanded
- SSO/SAML/OIDC.
- SCIM/user provisioning.
- Private networking.
- Customer-managed model/provider options.
- Advanced audit/compliance controls.
- Enterprise deployment models.

## SaaS start gate

Do not begin substantial SaaS implementation until:
1. Core Stage A correctness is strong and measurable.
2. Core Stage B reliability is adequate for real users.
3. OSS installation/onboarding is usable.
4. External users or prospective buyers provide evidence of demand.
5. We can identify which capabilities users will actually pay for.

---

# Roadmap maintenance

When completing a milestone:
1. Move it into **Completed**.
2. Update **Current checkpoint** with measured evidence.
3. Record newly discovered gaps under the active stage.
4. Reorder future work if benchmark/user evidence changes priorities.
5. Keep SaaS work deferred unless its start gate is satisfied.

The roadmap is a decision document, not a promise to implement every listed feature.
