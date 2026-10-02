# Data Pilot

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-blue)](pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com)
[![Code style](https://img.shields.io/badge/code%20style-clean%20architecture-4caf50.svg)](src/datapilot)

> **Data Pilot** is an open-source, self-hostable AI data intelligence and natural-language-to-SQL platform.

---

## 1. What is Data Pilot?

Data Pilot enables users and downstream services to query relational and analytical databases using natural language. Unlike generic chatbot wrappers that hallucinate table structures or pass unfiltered prompts to models, Data Pilot is engineered as an enterprise-grade, deterministic data access engine.

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

### Concrete Example

**User:** *"How many on-order vessels does MSC have?"*

Data Pilot coordinates:
1. **Semantic Understanding:** Recognizes *"on-order"* as a business status and *"MSC"* as a carrier entity value.
2. **Schema Discovery:** Resolves the entities to underlying tables (e.g. `vessels`, `carriers`).
3. **Template / Rule Selection:** Checks if a pre-compiled query template or metric definition exists.
4. **SQL Generation:** Synthesizes dialect-correct SQL (e.g., PostgreSQL).
5. **SQL Safety Validation:** Verifies the query is strictly non-mutating (`SELECT`), applies limits, and tests against SQL injection.
6. **Execution & Explanation:** Executes query against the target database and explains the resulting rows in natural language.

---

## 2. Core Architectural Principles

- **Open-Source First (No SaaS Bloat):** The engine contains zero multi-tenancy code, billing stubs, user subscriptions, or cloud vendor lock-in. Future SaaS layers can wrap this engine cleanly via APIs without modifying core logic.
- **Database-Agnostic:** Business rules and semantic graphs are decoupled from engine specifics. PostgreSQL is our first provider, with clean protocols for MySQL, SQL Server, Snowflake, BigQuery, and SQLite.
- **LLM-Agnostic:** Swappable provider abstraction. Works with Google Gemini, OpenAI, Anthropic, or local open-weights models (Ollama, vLLM).
- **Business Logic Outside Prompts:** Templates, metrics, column mappings, entity synonyms, and schema metadata exist as typed Python objects and structured models, not buried in prompt strings.
- **Deterministic and Testable:** Core modules, parsers, and validators are fully testable without invoking external AI APIs.
- **Security First:** No LLM-generated SQL ever executes without explicit AST and safety validation.

---

## 3. Project Structure

```text
data-pilot/
├── src/
│   └── datapilot/
│       ├── api/                   # HTTP API layer (FastAPI routers, lifespan, CORS)
│       │   ├── routes/            # Route handlers (health, info, etc.)
│       │   └── app.py             # FastAPI factory create_app()
│       ├── application/           # Application orchestration & use-case services
│       │   └── services/          # HealthService, execution coordinators
│       ├── core/                  # Cross-cutting concerns
│       │   ├── config.py          # Pydantic Settings & environment variables
│       │   ├── logging.py         # Structured logging configuration
│       │   └── exceptions.py      # Core domain exception hierarchy
│       ├── domain/                # Enterprise domain entities & protocol interfaces
│       │   ├── models.py          # TableMetadata, SchemaMetadata, QueryResult, etc.
│       │   └── interfaces/        # Dependency inversion contracts:
│       │       ├── database.py    # DatabaseProvider protocol
│       │       ├── llm.py         # LLMProvider protocol
│       │       ├── metadata.py    # MetadataProvider protocol
│       │       ├── sql_generator.py # SQLGenerator protocol
│       │       └── sql_validator.py # SQLValidator protocol
│       ├── infrastructure/        # Outgoing adapters (Postgres, Gemini, etc.)
│       └── main.py                # Server execution entry point (uvicorn runner)
├── tests/
│   ├── conftest.py                # Pytest fixtures and TestClient configuration
│   ├── unit/                      # Fast deterministic unit tests
│   │   ├── test_config.py         # Configuration loading and overrides
│   │   └── test_domain_interfaces.py # Interface contracts and protocol checks
│   └── integration/               # API integration tests
│       └── test_health_api.py     # Health, readiness, OpenAPI validation
├── docs/                          # Architecture & design documentation
│   └── architecture.md
├── .env.example                   # Annotated template for environment variables
├── .gitignore                     # Production Python gitignore
├── pyproject.toml                 # Standard packaging and dependency management
├── README.md                      # Project documentation
└── LICENSE                        # Apache 2.0 Open Source License
```

---

## 4. Current Status: Foundation (Phase 1)

This repository currently implements **Phase 1: Architectural Foundation**:

- [x] Standard `pyproject.toml` configuration and packaging
- [x] FastAPI application factory and route management
- [x] Environment configuration via Pydantic Settings
- [x] Protocol abstractions for `LLMProvider`, `DatabaseProvider`, `MetadataProvider`, `SQLGenerator`, and `SQLValidator`
- [x] Structured domain models (`SchemaMetadata`, `TableMetadata`, `QueryResult`, `SQLValidationResult`)
- [x] Liveness (`/health`), readiness (`/health/ready`), and metadata (`/info`) endpoints
- [x] Structured logging and domain exception hierarchy
- [x] Complete pytest test suite with 100% passing tests

---

## 5. Local Development Setup

### Prerequisites

- Python 3.10, 3.11, or 3.12
- `pip` and virtual environment tool (`venv` or `uv`)

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

Edit `.env` to configure your database connection string and provider preferences when ready.

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
- **Health Probe:** `http://localhost:8000/health`
- **System Info:** `http://localhost:8000/info`

---

## 6. How the Project Will Evolve

Development proceeds in clear modular phases:

1. **Phase 1: Foundation (Current)**
   - Core packaging, FastAPI application, typed domain contracts, and health probes.
2. **Phase 2: Database Provider & Schema Discovery**
   - PostgreSQL adapter implementation via SQLAlchemy, schema reflection, and metadata caching.
3. **Phase 3: SQL Safety & AST Validator**
   - Read-only AST parser, statement sanitization, table whitelist verification, and injection defense.
4. **Phase 4: LLM Provider Integration & Semantic Catalog**
   - Google Gemini provider adapter, business definitions catalog, and metric registries.
5. **Phase 5: NL-to-SQL Orchestration Engine**
   - Intent classifier, schema pruning, few-shot contextual prompt assembly, and response explanation.
6. **Phase 6: Web Dashboard & Query Interface**
   - Self-hostable interactive explorer UI for testing queries and inspecting data catalogs.

---

## License

Data Pilot is open-source software licensed under the [Apache License, Version 2.0](LICENSE).
