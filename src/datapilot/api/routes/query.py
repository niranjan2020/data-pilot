"""Natural-language query endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from datapilot.application.services.query_orchestrator import QueryOrchestrator
from datapilot.core.config import Settings, get_settings
from datapilot.core.exceptions import ConfigurationError
from datapilot.domain.query import QueryRequest, QueryResponse
from datapilot.infrastructure.database.postgresql import PostgreSQLDatabaseProvider
from datapilot.infrastructure.llm.gemini import GeminiLLMProvider
from datapilot.infrastructure.metadata.semantic_postgresql import PostgreSQLSemanticCatalogProvider
from datapilot.infrastructure.sql.validator import SQLGlotValidator

router = APIRouter(prefix="/api", tags=["Query"])


async def get_query_orchestrator(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> QueryOrchestrator:
    """Create the core query graph once per application instance."""
    existing = getattr(request.app.state, "query_orchestrator", None)
    if existing is not None:
        return existing

    if not settings.default_database_url:
        raise ConfigurationError("DEFAULT_DATABASE_URL is required for /api/query")
    if settings.gemini_api_key is None:
        raise ConfigurationError("GEMINI_API_KEY is required for the Gemini query provider")
    if settings.default_llm_provider != "gemini":
        raise ConfigurationError(
            "The first query API implementation supports only the configured Gemini provider"
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

    llm = GeminiLLMProvider(
        api_key=settings.gemini_api_key.get_secret_value(),
        model=settings.gemini_model,
    )
    orchestrator = QueryOrchestrator(
        database_provider=database,
        sql_validator=SQLGlotValidator(),
        llm_provider=llm,
        semantic_catalog_provider=semantic_catalog,
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
        "Runs the Data Pilot semantic/template/LLM query workflow. "
        "Generated SQL is validated before execution and only read-only queries are allowed."
    ),
)
async def query(
    payload: QueryRequest,
    orchestrator: QueryOrchestrator = Depends(get_query_orchestrator),
) -> QueryResponse:
    """Execute one natural-language database question."""
    return await orchestrator.query(payload)
