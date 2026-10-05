# Data Pilot Roadmap

> Living roadmap for the Data Pilot open-source core and future SaaS product.
>
> **Rule:** update this file whenever a milestone is completed, reprioritized, or a benchmark exposes a new reliability gap. Benchmark evidence, not feature speculation, drives Stage A.

**Last updated:** 2026-10-05  
**Current focus:** Core OSS — Stage A: NL-to-SQL correctness and evaluation  
**Current semantic evaluation baseline:** 25/25 passed (100.0%) after the first A2 coverage-expansion slice.  
**Current targeted correctness/orchestrator unit baseline:** 51/51 expected after the latest composed-grouping regression addition; prior run 50/50 passing.

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

#### A3. Time benchmark integration — CURRENT
- Version representative governed time-dimension evaluation metadata.
- Add last month, YTD, last N days, monthly trend, MoM, YoY, and grouping-only cases.
- Assert `time_filter_alignment` and `time_grain_alignment`.
- Include wrong-column, wrong-boundary, and wrong-grain negative cases.

#### A4. Failure taxonomy and reporting
Benchmark results should distinguish failures originating from:
- semantic retrieval,
- semantic resolution,
- ambiguity/clarification,
- time interpretation,
- SQL generation,
- AST/safety validation,
- governed correctness,
- execution,
- result correctness.

Add category-level pass rates so an overall score does not hide weak areas.

#### A5. Stage A exit criteria
Stage A is complete when:
- Core correctness unit suites remain green.
- Evaluation contains broad realistic coverage rather than a small happy-path set.
- No known systematic false positives/false negatives exist in deterministic correctness checks.
- Clarification/follow-up/time/join/fan-out paths have benchmark coverage.
- Unsupported questions fail safely rather than hallucinating.
- Benchmark failures are isolated product gaps, not missing evaluation plumbing.
- We have a stable measured baseline suitable for an OSS alpha.

Do **not** choose an arbitrary 100% benchmark target by weakening expectations. Correctness and explainability matter more than the headline score.

---

## Next — Stage B: Robustness and query-engine hardening

Begin only after Stage A is strong.

Planned:
- Bounded SQL correction/retry using structured validator feedback.
- Execution-error recovery where correction is safe.
- Explicit unsupported-question handling.
- Stronger dialect isolation while PostgreSQL remains the first-class provider.
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
