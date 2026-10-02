# Data Pilot Architecture & Technical Specification

## Architectural Overview

Data Pilot is structured as a **Modular Monolith** adhering to Clean Architecture / Hexagonal principles (Ports & Adapters).

```text
                      ┌──────────────────────────┐
                      │      HTTP API Layer      │
                      │  (FastAPI, Endpoints)    │
                      └────────────┬─────────────┘
                                   │
                      ┌────────────▼─────────────┐
                      │    Application Layer     │
                      │  (Services, Orchestrator)│
                      └────────────┬─────────────┘
                                   │
                      ┌────────────▼─────────────┐
                      │       Domain Layer       │
                      │  (Protocols & Models)    │
                      └────────────▲─────────────┘
                                   │  implements
              ┌────────────────────┴────────────────────┐
              │                                         │
┌─────────────┴─────────────┐             ┌─────────────┴─────────────┐
│    Database Adapters      │             │       LLM Adapters        │
│ (PostgreSQL, Snowflake)   │             │ (Gemini, OpenAI, Local)   │
│       [PLANNED]           │             │        [PLANNED]          │
└───────────────────────────┘             └───────────────────────────┘
```

---

## Current Status: Phase 1 (Foundation)

### Implemented Now:
- **Python Package:** `datapilot` package managed via `pyproject.toml`.
- **HTTP API Layer:** FastAPI application factory (`create_app`), lifespan management, and safe CORS defaults.
- **Configuration:** Pydantic Settings with environment variable loading, `SecretStr` masking for API credentials, and safe local development defaults.
- **Logging:** Structured logging configuration.
- **Exceptions:** Domain exception hierarchy (`DataPilotError`, `ProviderError`, `DatabaseError`, `LLMError`, etc.).
- **Domain Models:** Typed Pydantic models for `SchemaMetadata`, `TableMetadata`, `ColumnMetadata`, `QueryResult`, `SQLValidationResult`, `LLMMessage`, `LLMResponse`.
- **Domain Protocols:** Dependency inversion contracts using `@runtime_checkable` `typing.Protocol`:
  - `DatabaseProvider`
  - `LLMProvider`
  - `MetadataProvider`
  - `SQLGenerator`
  - `SQLValidator`
- **Health Endpoints:** `/health` (liveness), `/health/ready` (readiness checking configuration presence), and `/info` (system metadata).
- **Test Suite:** Initial pytest unit and integration tests.

### Planned for Future Phases (Not Yet Implemented):
- Concrete database adapters (PostgreSQL, MySQL, Snowflake, etc.)
- Automatic schema discovery, introspection, and catalog persistence
- Concrete LLM adapters (Google Gemini, OpenAI, Anthropic, Ollama/vLLM)
- Natural language intent detection and semantic entity resolution
- Business template matching and rule evaluation
- Dialect-specific SQL generation
- AST parsing and SQL safety validation implementation
- Query execution and natural language result explanation
- Frontend web interface
- Containerization & Docker compose setup
- Future SaaS wrapping layer (external to open-source core)

---

## Key Architectural Decisions

### 1. Dependency Inversion
All application and domain modules depend exclusively on abstract protocol contracts declared in `datapilot.domain.interfaces`. Concrete infrastructure adapters will plug into these interfaces without coupling the core engine to any specific database driver or LLM vendor SDK.

### 2. Protocol Contracts

| Interface | Module | Purpose |
| :--- | :--- | :--- |
| `DatabaseProvider` | `datapilot.domain.interfaces.database` | Connection check, schema reflection, and query execution |
| `LLMProvider` | `datapilot.domain.interfaces.llm` | Text generation and structured output parsing |
| `MetadataProvider` | `datapilot.domain.interfaces.metadata` | Enriched business metadata persistence |
| `SQLGenerator` | `datapilot.domain.interfaces.sql_generator` | Synthesis of SQL from question + schema |
| `SQLValidator` | `datapilot.domain.interfaces.sql_validator` | Safety validation, AST parsing, and read-only checks |

### 3. Planned Safety Architecture
Data Pilot is designed to enforce a strict security perimeter in subsequent phases:
- **No Direct Execution of Raw LLM Output:** Generated SQL must pass through the `SQLValidator` before execution.
- **Read-Only Enforcement:** Queries will be parsed and validated to ensure non-mutating semantics (`SELECT` only).
- **Resource Limits:** Execution timeouts and query result caps will be applied by default.

### 4. Evolution Towards SaaS
When enterprise or SaaS requirements emerge in the future, the open-source core will remain untouched. A separate wrapper service will handle multi-tenancy, authentication tokens, and billing, delegating core NL-to-SQL workflows to Data Pilot via standard Python calls or HTTP endpoints.
