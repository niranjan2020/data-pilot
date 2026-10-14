# Architecture decisions and rationale

These are current product design directions, not a certification that every behavior is implemented.

## ADR-001 — Minimal semantic configuration
**Decision:** A selected single physical table should support ordinary filters, grouping, ordering, and straightforward aggregations using discovered columns. Governed semantic metrics are valuable for business-specific calculations, but are not mandatory for every simple question.

**Why:** Forcing full modeling before a first query undermines Data Pilot's fast-onboarding goal. Unknown business terms must still trigger clarification or explicit definition.

## ADR-002 — Published relationships for cross-entity SQL
**Decision:** Join authorization is separate from discovering possible foreign-key relationships. Cross-entity routes must be selected, currently published, and verified against generated SQL, including nested joins and join type/key/cardinality constraints.

**Why:** A plausible join can be both unauthorized and semantically wrong. Multiple authorization checks may enforce distinct safety guarantees and should not be removed merely because they look repetitive.

## ADR-003 — One evolving SQL generation and validation pipeline
**Decision:** Continue evolving the existing intent contract, SQL generator, SQLGlot validators, repair helpers, and query orchestrator. Do not create an independent second compiler, planner, or template-first execution engine.

**Why:** Parallel logic produces contradictory interpretations and harder-to-debug regressions. Reuse deterministic validations to constrain LLM output.

## ADR-004 — Semantic accuracy is not execution success
**Decision:** Evaluate actual metric meaning, filters, cohort preservation, time scope, grouping grain, join fan-out, and result shape. Report SQL execution and reviewed semantic correctness separately.

**Why:** A syntactically valid, executable query can answer a different question. The 49-question Astra evaluation remains a release gate until expectations are independently reviewed.

## ADR-005 — Safe, bounded SQL repair
**Decision:** Repair only when the intended correction is unambiguous. Re-run read-only safety, dataset and relationship authorization, semantic correctness, and policy checks after modifications; otherwise fail closed with useful diagnostics.

**Why:** A repair that silently changes meaning or skips authorization is worse than a clear rejection.

## ADR-006 — OSS first, hosted SaaS later
**Decision:** Keep self-hosted NL-to-SQL and future NL-to-API extensibility provider-neutral. Introduce multi-tenancy, hosted billing, and commercial control-plane capabilities later without making them requirements for OSS use.

**Why:** Simple installation and a credible open-source core support adoption and independent evaluation.

## ADR-007 — Wren AI is a capability benchmark, not a blueprint
**Decision:** Study reusable semantic expressions, verified examples, onboarding, and governance in Wren AI and similar projects. Adopt capabilities that improve accuracy and usability while preserving Data Pilot's existing architecture and low-configuration approach.

**Why:** Matching user outcomes matters more than copying another product's internal architecture.

For implementation-specific gaps and unresolved risks, see [the architecture audit](../architecture_gap_audit_2026-10-13.md).
