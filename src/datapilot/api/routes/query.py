"""Natural-language query endpoint composition root."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from datapilot.application.services.query_orchestrator import QueryOrchestrator
from datapilot.core.config import Settings, get_settings
from datapilot.core.exceptions import ConfigurationError
from datapilot.domain.query import QueryRequest, QueryResponse
from datapilot.infrastructure.database.postgresql import PostgreSQLDatabaseProvider
from datapilot.infrastructure.llm.gemini import GeminiLLMProvider
from datapilot.infrastructure.metadata.semantic_postgresql import PostgreSQLSemanticCatalogProvider
from datapilot.infrastructure.sql.llm_generator import LLMBackedSQLGenerator
from datapilot.infrastructure.sql.validator import SQLGlotValidator

router = APIRouter(prefix="/api", tags=["Query"])


async def get_query_orchestrator(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> QueryOrchestrator:
    """Compose concrete adapters at the HTTP boundary, not inside the core."""
    existing = getattr(request.app.state, "query_orchestrator", None)
    if existing is not None:
        return existing

    if not settings.default_database_url:
        raise ConfigurationError("DEFAULT_DATABASE_URL is required for /api/query")
    if settings.gemini_api_key is None:
        raise ConfigurationError(
            "An LLM provider credential is required for the configured SQL generator"
        )

    database = PostgreSQLDatabaseProvider(
        database_url=settings.default_database_url,
        pool_size=settings.database_pool_size,
        default_timeout_seconds=settings.database_query_timeout_seconds,
    )

    semantic_database_url = settings.metadata_database_url or settings.default_database_url
    semantic_catalog = PostgreSQLSemanticCatalogProvider(
        database_url=semantic_database_url,
        pool_size=settings.metadata_database_pool_size,
    )
    await semantic_catalog.initialize()

    # Provider-specific composition is deliberately isolated here. The
    # QueryOrchestrator only receives the generic SQLGenerator port.
    if settings.default_llm_provider != "gemini":
        raise ConfigurationError(
            "No adapter is registered for the configured LLM provider yet. "
            "The core query engine remains provider-independent."
        )

    llm = GeminiLLMProvider(
        api_key=settings.gemini_api_key.get_secret_value(),
        model=settings.gemini_model,
    )
    sql_generator = LLMBackedSQLGenerator(llm)

    orchestrator = QueryOrchestrator(
        database_provider=database,
        sql_validator=SQLGlotValidator(),
        sql_generator=sql_generator,
        semantic_catalog_provider=semantic_catalog,
        query_timeout_seconds=settings.database_query_timeout_seconds,
    )

    request.app.state.query_database = database
    request.app.state.query_semantic_catalog = semantic_catalog
    request.app.state.query_llm = llm
    request.app.state.query_orchestrator = orchestrator
    return orchestrator


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Ask a natural-language database question",
    description=(
        "Runs the Data Pilot semantic-resolution and SQL-generation workflow. "
        "Generated SQL is validated before execution and only read-only queries are allowed."
    ),
)
async def query(
    payload: QueryRequest,
    orchestrator: QueryOrchestrator = Depends(get_query_orchestrator),
) -> QueryResponse:
    """Execute one natural-language database question."""
    return await orchestrator.query(payload)
