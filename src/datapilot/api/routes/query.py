"""Natural-language query endpoint composition root."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from datapilot.application.services.query_orchestrator import QueryOrchestrator
from datapilot.application.services.semantic_context import SemanticContextAssembler
from datapilot.core.config import Settings, get_settings
from datapilot.core.exceptions import ConfigurationError
from datapilot.domain.query import QueryRequest, QueryResponse
from datapilot.infrastructure.database.postgresql import PostgreSQLDatabaseProvider
from datapilot.infrastructure.llm.gemini import GeminiLLMProvider
from datapilot.infrastructure.metadata.semantic_postgresql import PostgreSQLSemanticCatalogProvider
from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider
from datapilot.infrastructure.metadata.query_history import PostgreSQLQueryHistoryStore
from datapilot.infrastructure.sql.llm_generator import LLMBackedSQLGenerator
from datapilot.infrastructure.semantic.qdrant import QdrantSemanticIndex
from datapilot.infrastructure.sql.validator import SQLGlotValidator

router = APIRouter(prefix="/api", tags=["Query"])


async def get_query_history_store(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> PostgreSQLQueryHistoryStore:
    """Return the shared query-history store backed by platform metadata PostgreSQL."""
    existing = getattr(request.app.state, "query_history_store", None)
    if existing is not None:
        return existing

    database_url = settings.metadata_database_url or settings.default_database_url
    if not database_url:
        raise ConfigurationError("METADATA_DATABASE_URL is required for query history")
    store = PostgreSQLQueryHistoryStore(
        database_url=database_url,
        pool_size=settings.metadata_database_pool_size,
    )
    await store.initialize()
    request.app.state.query_history_store = store
    return store


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
    semantic_retriever = QdrantSemanticIndex(
        settings.qdrant_url, settings.qdrant_collection, settings.embedding_model
    )
    metadata_catalog = PostgreSQLMetadataProvider(
        database_url=semantic_database_url,
        pool_size=settings.metadata_database_pool_size,
    )
    semantic_context_assembler = SemanticContextAssembler(metadata_catalog)

    orchestrator = QueryOrchestrator(
        database_provider=database,
        sql_validator=SQLGlotValidator(),
        sql_generator=sql_generator,
        semantic_catalog_provider=semantic_catalog,
        query_timeout_seconds=settings.database_query_timeout_seconds,
        semantic_retriever=semantic_retriever,
        semantic_context_assembler=semantic_context_assembler,
    )

    request.app.state.query_database = database
    request.app.state.query_semantic_catalog = semantic_catalog
    request.app.state.query_metadata_catalog = metadata_catalog
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
    history: PostgreSQLQueryHistoryStore = Depends(get_query_history_store),
) -> QueryResponse:
    """Execute one natural-language database question and persist its lineage."""
    response = await orchestrator.query(payload)
    await history.record(payload, response)
    return response


@router.get("/query/history", summary="List recent query history")
async def list_query_history(
    source_name: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    history: PostgreSQLQueryHistoryStore = Depends(get_query_history_store),
) -> list[dict]:
    """List recent persisted queries, newest first."""
    return await history.list(source_name=source_name, limit=limit)


@router.get("/query/history/{history_id}", summary="Get query history detail")
async def get_query_history(
    history_id: int,
    history: PostgreSQLQueryHistoryStore = Depends(get_query_history_store),
) -> dict:
    """Return a historical query together with its saved response and trace."""
    item = await history.get(history_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Query history item not found")
    return item
