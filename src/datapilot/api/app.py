"""FastAPI application factory and middleware configuration."""

import asyncio
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from datapilot.api.routes.health import router as health_router
from datapilot.api.routes.data_sources import router as data_sources_router
from datapilot.api.routes.semantic import router as semantic_router
from datapilot.api.routes.query import router as query_router
from datapilot.api.routes.setup import router as setup_router
from datapilot.core.config import Settings, get_settings
from datapilot.core.exceptions import DataPilotError
from datapilot.core.logging import get_logger, setup_logging
from datapilot.infrastructure.llm.validation import ConfiguredAIProviderValidator
from datapilot.infrastructure.health import LocalRuntimeHealthChecker
from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider
from datapilot.infrastructure.secrets.local_env import LocalEnvAIProviderSecretStore

logger = get_logger("datapilot.api")


def _configure_windows_asyncio_policy() -> None:
    """Use the selector loop required by psycopg async on Windows."""
    if sys.platform == "win32" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        policy_type = asyncio.WindowsSelectorEventLoopPolicy
        if not isinstance(asyncio.get_event_loop_policy(), policy_type):
            asyncio.set_event_loop_policy(policy_type())


_configure_windows_asyncio_policy()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager for startup and shutdown events."""
    settings = getattr(app.state, "settings", get_settings())
    setup_logging(settings)
    logger.info(
        "Initializing %s v%s in %s environment",
        settings.app_name,
        settings.app_version,
        settings.environment,
    )
    yield

    for state_name in ("query_database", "query_semantic_catalog", "query_llm", "query_history_store", "setup_metadata"):
        provider = getattr(app.state, state_name, None)
        if provider is not None:
            close = getattr(provider, "close", None)
            if close is not None:
                await close()

    logger.info("Shutting down %s", settings.app_name)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Create and configure a new FastAPI application instance."""
    app_settings = settings or get_settings()

    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        description=(
            "Open-source, self-hostable AI data intelligence platform converting natural "
            "language questions into validated SQL."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.state.settings = app_settings
    app.dependency_overrides[get_settings] = lambda: app_settings

    # Local OSS composition. Managed deployments can replace these state-bound
    # adapters with vault-backed secret storage/provider validators.
    app.state.ai_secret_store = LocalEnvAIProviderSecretStore("/app/data/secrets/ai-provider.env")
    app.state.ai_provider_validator = ConfiguredAIProviderValidator(app.state.ai_secret_store)
    # Metadata is an explicit platform dependency. Never fall back to the
    # customer/default query database: onboarding owns that connection separately.
    app.state.setup_metadata = (
        PostgreSQLMetadataProvider(app_settings.metadata_database_url)
        if app_settings.metadata_database_url else None
    )
    app.state.runtime_health_checker = LocalRuntimeHealthChecker(app.state.setup_metadata)

    if app_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.cors_origins,
            allow_credentials=app_settings.cors_allow_credentials,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )

    @app.exception_handler(DataPilotError)
    async def datapilot_exception_handler(request: Request, exc: DataPilotError) -> JSONResponse:
        logger.error("DataPilot error occurred: %s", exc, exc_info=app_settings.debug)
        return JSONResponse(
            status_code=400,
            content={
                "error": exc.__class__.__name__,
                "message": exc.message,
                "details": exc.details,
            },
        )

    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse(
            content={
                "name": app_settings.app_name,
                "version": app_settings.app_version,
                "description": "Open-source AI data intelligence & natural-language-to-SQL platform",
                "documentation": "/docs",
                "health": "/health",
                "info": "/info",
                "query": "/api/query",
                "status": "operational",
            }
        )

    app.include_router(health_router)
    app.include_router(data_sources_router)
    app.include_router(semantic_router)
    app.include_router(query_router)
    app.include_router(setup_router)

    return app
