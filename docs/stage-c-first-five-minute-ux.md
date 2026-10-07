# Stage C First-Five-Minute UX Contract

Stage C north star: **clean machine -> connected database -> first trustworthy governed answer in <= 5 minutes**.

This document is a UI contract, not frontend orchestration logic. The UI renders backend setup state and invokes backend actions; it must not independently infer readiness or duplicate query-engine governance.

## TTFA instrumentation

Record these monotonic milestones for product/evaluation telemetry. They are operational timings, never credentials, prompts, SQL results, or customer data.

| Milestone | Meaning |
| --- | --- |
| setup_started | First onboarding interaction for this setup run |
| ai_provider_ready | Provider/model credential validation succeeded |
| data_source_ready | Target database connection validation succeeded |
| schema_discovery_completed | Initial physical discovery completed |
| data_selection_ready | User approved the starting governed data set |
| semantic_model_ready | Required semantic review/approval completed |
| first_question_submitted | First governed question entered |
| first_answer_completed | First trustworthy governed answer completed |

Primary metric: first_answer_completed - setup_started. Supporting durations are derived between milestones. A restart may resume persisted readiness state; timing instrumentation must distinguish a resumed setup run from the original run rather than fabricating missing timestamps.

## Screen contract

### 1. Welcome
Backend source: GET /api/setup/status and GET /api/setup/readiness.

- If ready=false, route to current_step.
- If ready=true, leave onboarding and open Ask Data Pilot.
- Never infer completion from environment variables or browser state.

### 2. AI Provider
Backend state: ai_provider.

Inputs: provider, model, optional provider endpoint/deployment fields, credential. Actions: save + validate, retry. Success requires backend validation. Secrets are write-only from the normal product surface and must never be re-rendered by read APIs.

### 3. Data Source
Backend state: data_source.

PostgreSQL-first connection form and Test Connection action. Success requires backend validation, not merely populated fields. Stage C3 defines connection diagnostics and secret handling.

### 4. Discover & Select
Backend state: data_selection.

Show discovery progress, schemas/tables/views and a recommended starting set. User reviews and approves the governed starting set. Large databases must not require selecting everything.

### 5. Semantic Review
Backend state: semantic_review.

Show AI-assisted semantic suggestions with evidence. Each suggestion is visibly unapproved until the user approves, edits, or rejects it. Approved deterministic configuration becomes query-time authority.

### 6. Ready / Ask
Backend state: ready.

Submit through the existing production query API. Display answer, result shape, deterministic explanation and optional SQL from backend contracts. The UI must not recreate correctness, recovery, or explanation logic.

## Resumption rules

- Persisted backend facts are authoritative after refresh/restart.
- The first incomplete step is the resumable step.
- Later steps remain blocked until prerequisites complete.
- Reconfiguring a validated dependency invalidates readiness before replacement validation.
- An interrupted action may be retried; the UI must not mark it complete optimistically.
- Product readiness and runtime health remain separate concepts.

## C1 handoff to frontend

The frontend needs deterministic backend state plus action endpoints. C2-C5 add concrete deployment, database connection, discovery and semantic-bootstrap actions behind this contract. Frontend screens must not invent alternate setup state.
