# Data Pilot Roadmap

> Living roadmap for the Data Pilot open-source core and future SaaS product.
>
> **Rule:** update this file whenever a milestone is completed, reprioritized, or a benchmark exposes a new reliability gap. Benchmark evidence, not feature speculation, drives Stage A.

**Last updated:** 2026-10-06  
**Current focus:** Core OSS — Stage B: robustness and production-quality query engine  
**Current semantic evaluation baseline:** 39/39 passed (100.0%) through the live production pipeline after B4 dialect isolation (p50 2.986 s, p95 4.249 s).  
**Current full automated regression baseline:** 331/331 passed after B4 dialect isolation.

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

### Current checkpoint — 2026-10-05

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

## Stage B: Robustness and query-engine hardening — CURRENT

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

### B5. Query timeout and resource-policy hardening — CURRENT
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

B5 implementation order:
- **B5.2:** make row/limit policy deterministic and fail-closed, including aggregate/grouped result bounding and non-literal LIMIT handling.
- **B5.3:** validate policy configuration invariants and make the effective timeout/resource budget explicit in composition and trace.
- **B5.4:** add timeout/cancellation and bounded-result regressions across normal execution, B1, and B2; close B5 only after the full suite and unchanged live benchmark pass.

Remaining:
- Query timeout/resource-policy hardening.
- Better diagnostic traces and explainability.
- Regression corpus growth from real OSS usage.

Avoid autonomous/unbounded agent loops.

---

## Next — Stage C: Open-source product experience

Make the reliable engine usable by people who did not build it.

Planned flow:
```text
Connect database
  -> discover schema
  -> configure/approve semantic model
  -> ask questions
  -> clarify ambiguity
  -> generate and validate SQL
  -> inspect results/chart/explanation
```

Planned work:
- Connection/onboarding experience.
- Schema browser.
- Semantic model/business-rule configuration UI.
- Metric/entity/relationship/time-dimension management.
- Query trace/explainability UI.
- Result visualization.
- Easy local Docker startup.
- Sample database and guided demo.

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
