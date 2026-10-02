# Data Pilot

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-blue)](pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com)
[![Architecture](https://img.shields.io/badge/architecture-modular%20monolith-4caf50.svg)](docs/architecture.md)

> **Data Pilot** is an open-source, self-hostable AI data intelligence and natural-language-to-SQL platform.

---

## 1. What is Data Pilot?

Data Pilot is being built to enable users and downstream services to query relational and analytical databases using natural language. Rather than acting as a generic chatbot wrapper that passes raw prompts to an LLM, Data Pilot is designed as a deterministic, structured data access engine.

### The Core Vision

```text
User asks a question in natural language
        ↓
Data Pilot understands the user's intent
        ↓
Discovers / retrieves relevant schema and business metadata
        ↓
Uses templates & business rules when applicable
        ↓
Generates dialect-specific SQL when required
        ↓
Validates the SQL (Read-only verification & AST safety checks)
        ↓
Executes the SQL against the connected database
        ↓
Returns structured results
        ↓
Explains and summarizes the result in natural language
```

### Planned Workflow Example

**User:** *"How many on-order vessels does MSC have?"*

Data Pilot is designed to coordinate:
1. **Semantic Understanding:** Recognize *"on-order"* as a business concept and *"MSC"* as an entity/value.
2. **Schema Discovery:** Resolve the concepts to relevant database tables and columns.
3. **Template / Rule Selection:** Check if a pre-defined query template or metric rule exists.
4. **SQL Generation:** Synthesize dialect-appropriate SQL when a template is not present.
5. **SQL Safety Validation:** Validate that the SQL is safe, read-only (`SELECT`), and complies with AST safety policies before execution.
6. **Execution & Explanation:** Execute query against the connected database and explain the structured results in natural language.

---

## 2. Core Architectural Principles

- **Open-Source First (No SaaS Bloat):** The engine contains zero multi-tenancy code, billing stubs, user subscriptions, or cloud vendor lock-in. A future SaaS layer can be added externally without rewriting the core engine.
- **Database-Agnostic:** Business logic and semantic definitions are decoupled from database specifics. PostgreSQL will be the first supported provider, with abstract protocols for Snowflake, MySQL, BigQuery, and others.
- **LLM-Agnostic:** Pluggable provider protocol. Designed to support Google Gemini, OpenAI, Anthropic, or local open-weights models.
- **Business Logic Outside Prompts:** Templates, metrics, column mappings, entity synonyms, and schema metadata have typed Python representations—not embedded solely inside prompt strings.
- **Deterministic and Testable:** Core modules, parsers, and validators are designed to be testable without requiring live LLM API calls.
- **Security First:** Generated SQL is designed to pass through validation before execution.

---

## 3. Project Structure

```text
data-pilot/
├── src/
│   └── datapilot/
│       ├── api/                   # HTTP API layer (FastAPI factory, lifespan, CORS)
│       │   ├── routes/            # Route handlers (health, info)
│       │   └── app.py             # FastAPI factory create_app()
│       ├── application/           # Application use-case services
│       │   └── services/          # HealthService
│       ├── core/                  # Cross-cutting concerns
│       │   ├── config.py          # Pydantic Settings & environment variables
│       │   ├── logging.py         # Structured logging setup
│       │   └── exceptions.py      # Core domain exception hierarchy
│       ├── domain/                # Enterprise domain entities & protocol contracts
│       │   ├── models.py          # TableMetadata, SchemaMetadata, QueryResult, etc.
│       │   └── interfaces/        # Dependency inversion protocols:
│       │       ├── database.py    # DatabaseProvider protocol
│       │       ├── llm.py         # LLMProvider protocol
│       │       ├── metadata.py    # MetadataProvider protocol
│       │       ├── sql_generator.py # SQLGenerator protocol
│       │       └── sql_validator.py # SQLValidator protocol
│       ├── infrastructure/        # Outgoing adapter skeletons (PostgreSQL, Gemini, etc.)
│       └── main.py                # Server execution entry point
├── tests/
│   ├── conftest.py                # Pytest fixtures and TestClient configuration
│   ├── unit/                      # Unit tests
│   │   ├── test_config.py         # Configuration loading, SecretStr, and CORS defaults
│   │   └── test_domain_interfaces.py # Interface contracts and protocol checks
│   └── integration/               # Integration tests
│       └── test_health_api.py     # Health, readiness, OpenAPI validation
├── docs/
│   └── architecture.md            # Technical specification & dependency inversion design
├── .env.example                   # Annotated template for environment variables
├── .gitignore                     # Python gitignore
├── pyproject.toml                 # Standard packaging and dependency management
├── README.md                      # Project documentation
└── LICENSE                        # Apache 2.0 Open Source License
```

---

## 4. Current Status: Phase 1 — Foundation

### Implemented:
- Project packaging and dependencies via `pyproject.toml`
- FastAPI application factory with lifespan and safe CORS defaults
- Configuration management using Pydantic Settings with `SecretStr` credential masking
- Structured logging
- Domain exception hierarchy
- Minimal domain models (`ColumnMetadata`, `TableMetadata`, `SchemaMetadata`, `QueryResult`, `SQLValidationResult`, `LLMMessage`, `LLMResponse`)
- Provider protocol interfaces (`DatabaseProvider`, `LLMProvider`, `MetadataProvider`, `SQLGenerator`, `SQLValidator`)
- Health and system information endpoints (`/health`, `/health/ready`, `/info`)
- Initial pytest test suite for configuration, protocol conformance, API endpoints, and PostgreSQL provider
- PostgreSQL database provider with pooled connections, schema introspection, and preliminary read-only execution boundary
- Deterministic schema discovery service with filtering, normalization, stable catalog versioning, and optional metadata persistence

### Next / Planned:
- Metadata/catalog persistence adapter
- SQL safety and AST validation implementation
- LLM provider integration (Google Gemini adapter)
- Semantic layer (templates, business rules, entity resolution)
- Natural-language-to-SQL orchestration engine
- Frontend web application

---

## 5. Local Development Setup

### Prerequisites

- Python 3.10, 3.11, or 3.12
- `pip` and virtual environment tool (`venv`)

### 1. Clone & Create Virtual Environment

```bash
git clone https://github.com/niranjan2020/data-pilot.git
cd data-pilot

python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies in Editable Mode

```bash
pip install -e ".[dev]"
```

### 3. Configure Environment

Copy the example environment file:

```bash
cp .env.example .env
```

Review `.env` to configure your database connection string and provider preferences when ready.

### 4. Run the Test Suite

```bash
pytest -v
```

### 5. Start the Local API Server

Using the `datapilot` CLI entry point:

```bash
datapilot
```

Or using `uvicorn` directly:

```bash
uvicorn datapilot.api.app:create_app --factory --host 0.0.0.0 --port 8000 --reload
```

Interactive API documentation will be available at:
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`
- **Health Liveness:** `http://localhost:8000/health`
- **Health Readiness:** `http://localhost:8000/health/ready`
- **System Info:** `http://localhost:8000/info`

---

## License

Data Pilot is open-source software licensed under the [Apache License, Version 2.0](LICENSE).
