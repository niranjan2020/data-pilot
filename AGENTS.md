# Data Pilot — instructions for coding agents

Read this file before modifying code. Read [ROADMAP.md](ROADMAP.md) for priorities and [the architecture gap audit](docs/architecture_gap_audit_2026-10-13.md) for known limitations. See [architecture documentation](docs/architecture/README.md) for design rationale.

## Mission
Data Pilot is a generic, open-source, self-hostable, LLM-agnostic natural-language-to-SQL product. Prioritize quick database onboarding, useful queries with minimal semantic configuration, trustworthy results, safe execution, and transparent diagnostics. Astra and AdventureWorks are test datasets, never domain-specific implementation assumptions. Future SaaS/multi-tenancy concerns should not complicate the OSS core prematurely.

## Architectural constraints
- Preserve straightforward single-table queries over discovered physical columns without requiring every attribute or grouping dimension to be published.
- Use explicit, verified, currently published relationships for physical cross-entity joins. Fail closed on missing/ambiguous routes, unsafe cardinality, or unauthorized joins. Do not weaken datasource/table boundaries.
- Use existing semantic catalog, SemanticIntentContract, relationship resolution, generation, SQLGlot-based correctness checks, orchestrator, and repair helpers. Do not build a parallel SQL compiler or duplicate rules engine.
- Distinguish a query that executes from a query that correctly answers the user's question. Check metrics, filters, categorical values, array expansion, grouping grain, time scope, ranking, comparison cohorts, join fan-out, and requested limits.
- Validate every generated or repaired SQL candidate against read-only safety, authorized datasets/joins, correctness, and execution policy before running it. Repairs must not bypass previous gates.
- Keep business definitions optional for obvious physical queries, but require clarification or approved semantics for ambiguous/high-impact metrics, mappings, and relationships. Never silently invent business rules.
- Protect customer data. Do not store customer query results by default or include secrets in commits.

## Development workflow
1. Inspect existing implementation and relevant tests before changing behavior. Reproduce failures and identify root causes; avoid accumulating regex patches and special cases.
2. Make cohesive, narrowly scoped changes using existing architecture. Add regression tests for fixes and negative/fail-closed cases.
3. Run targeted tests and then the full unit suite when the environment supports it. Clearly distinguish tests actually executed from tests merely suggested. If infrastructure, credentials, or dependencies are unavailable, report that limitation.
4. Review the diff and summarize changes, test evidence, and risks. **Do not commit, push, create PRs, or trigger GitHub Actions without explicit user approval for that task.** When approved, the user prefers direct commits to main rather than PRs.
5. Never reset Docker volumes, delete data, or execute destructive database operations without explicit permission. Avoid changing production-like configurations or exposing credentials.
6. Preserve user-visible diagnostics and evaluation traces when changing validators or repair behavior.

## Source of truth and status
- [ROADMAP.md](ROADMAP.md): product direction, prioritized backlog, acceptance gates.
- [docs/architecture/README.md](docs/architecture/README.md): architecture index and decisions.
- [docs/architecture_gap_audit_2026-10-13.md](docs/architecture_gap_audit_2026-10-13.md): dated, partial gap assessment; verify current code before treating findings as unresolved.
- Tests, code, and Git history are authoritative for implemented behavior. Prior chat discussions are context, not proof of passing tests.
