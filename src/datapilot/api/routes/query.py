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
from datapilot.infrastructure.sql.identifier_binding import SQLGlotIdentifierBinder
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
        sql_identifier_binder=SQLGlotIdentifierBinder(),
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
    conversation_context: dict | None = None
    if payload.follow_up_to_history_id is not None:
        parent = await history.get(payload.follow_up_to_history_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="Follow-up query history item not found")
        if payload.source_name and parent.get("source_name") != payload.source_name:
            raise HTTPException(
                status_code=400,
                detail="Follow-up context must come from the same data source",
            )
        saved_response = parent.get("response") or {}
        if saved_response.get("status") not in {"completed", "dry_run"}:
            raise HTTPException(
                status_code=400,
                detail="Only completed or dry-run queries can be used as follow-up context",
            )
        parent_trace = saved_response.get("trace") or {}
        parent_conversation = parent_trace.get("conversation_context") or {}
        prior_turns = list(parent_conversation.get("analytical_turns") or [])
        if not prior_turns:
            root_question = str(parent_conversation.get("previous_question") or "").strip()
            if root_question:
                prior_turns.append(root_question)
        parent_question = str(parent["question"]).strip()
        if parent_question and (not prior_turns or prior_turns[-1] != parent_question):
            prior_turns.append(parent_question)

        conversation_context = {
            "parent_history_id": parent["id"],
            "previous_question": parent["question"],
            "analytical_turns": prior_turns,
            "governed_datasets": parent_trace.get("governed_datasets") or [],
            "governed_entities": parent_trace.get("governed_entities") or [],
            "governed_metrics": parent_trace.get("governed_metrics") or [],
            "governed_business_rules": parent_trace.get("governed_business_rules") or [],
            "governed_time_dimensions": parent_trace.get("governed_time_dimensions") or [],
            "time_interpretation": parent_trace.get("time_interpretation") or {},
            "resolved_parameters": parent_trace.get("resolved_parameters") or {},
            "clarification_selections": parent_trace.get("clarification_selections") or {},
        }

    response = await orchestrator.query(
        payload,
        conversation_context=conversation_context,
    )
    history_id = await history.record(payload, response)
    response.history_id = history_id
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
