# Data Pilot — architecture documentation

This directory captures design intent and decisions for future contributors and coding agents. It complements [ROADMAP.md](../../ROADMAP.md) and the dated [architecture gap audit](../architecture_gap_audit_2026-10-13.md); it is not a claim that all capabilities are complete.

## Architecture principles

**Low-friction onboarding.** Discover tables, columns, keys, relationships, and candidate semantics. Allow straightforward queries against a selected physical table with little configuration. Ask for review only when a business definition, mapping, or cross-entity authorization cannot be established safely.

**Governed cross-entity analytics.** Relationship suggestions from discovery are not equivalent to approved join grants. Validate selected routes and the SQL's actual join keys, types, and grain against currently published relationships. Do not infer authorization from a plausible-looking column name.

**One query pipeline.** Reuse existing semantic context and intent contracts, LLM SQL generation, SQLGlot validators, bounded repair helpers, execution policies, and diagnostics. Improve these components incrementally rather than introducing competing planners or SQL compilers.

**Correctness beyond execution.** Passing SQL validation or returning rows is not proof of correct answers. Evaluate selected datasets, metrics, categorical and array filters, comparison cohorts, time grain, grouping, ranking, join fan-out, and output shape against the user's intent. Revalidate repaired SQL.

**Portable open-source core.** Keep the core domain- and LLM-provider-independent. Astra and AdventureWorks are acceptance fixtures. Multi-tenant SaaS, billing, hosted provider management, and commercial operations are later product layers, not prerequisites for using the OSS project.

## Reading order
1. [Agent instructions](../../AGENTS.md) — operating constraints for Codex and other agents.
2. [Product roadmap](../../ROADMAP.md) — priorities and acceptance gates.
3. [Architecture decisions](decisions.md) — the rationale behind core tradeoffs.
4. [Architecture gap audit](../architecture_gap_audit_2026-10-13.md) — dated risks and capability gaps; verify against current implementation.

## Evidence and change discipline
Keep architecture notes consistent with code and tests. Record meaningful design decisions here when they change; don't turn this directory into an automatically generated transcript. The Astra 49-question suite is an acceptance gate, not a passing semantic benchmark until expected interpretations and results are reviewed.
