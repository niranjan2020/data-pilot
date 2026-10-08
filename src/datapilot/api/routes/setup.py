"""First-run onboarding status API."""

import logging

_logger = logging.getLogger("datapilot.setup")

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from datapilot.application.setup_state import SetupStatus, derive_setup_status
from datapilot.application.data_source_onboarding import PostgreSQLConnectionInput, test_postgresql_connection
from datapilot.domain.interfaces.ai_configuration import (
    AIProviderConfiguration,
    AIProviderKind,
    AIProviderSecretInput,
)
from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider
from datapilot.infrastructure.secrets.local_env import LocalEnvAIProviderSecretStore
from datapilot.infrastructure.secrets.local_data_source import LocalDataSourceSecretStore
from datapilot.infrastructure.database.saved_connection import open_saved_data_source

router = APIRouter(prefix="/api/setup", tags=["Setup"])


class AIProviderSetupRequest(AIProviderConfiguration):
    api_key: str = ""


async def _setup_metadata(request: Request):
    settings = request.app.state.settings
    metadata = getattr(request.app.state, "setup_metadata", None)
    if metadata is not None:
        return metadata, False
    if not settings.metadata_database_url:
        raise HTTPException(status_code=503, detail="Platform metadata storage is not configured.")
    return PostgreSQLMetadataProvider(
        settings.metadata_database_url,
        pool_size=settings.metadata_database_pool_size,
    ), True


@router.get("/ai-provider", response_model=AIProviderConfiguration)
async def get_ai_provider(request: Request) -> AIProviderConfiguration:
    metadata, owns_metadata = await _setup_metadata(request)
    secret_store = getattr(request.app.state, "ai_secret_store", LocalEnvAIProviderSecretStore())
    try:
        configuration = await metadata.get_ai_provider_configuration()
        if configuration is None:
            raise HTTPException(status_code=404, detail="AI provider is not configured.")
        has_secret = await secret_store.has_ai_provider_secret(configuration.provider)
        return configuration.model_copy(update={"credential_configured": has_secret})
    finally:
        if owns_metadata:
            await metadata.close()


@router.put("/ai-provider", response_model=AIProviderConfiguration)
async def configure_ai_provider(payload: AIProviderSetupRequest, request: Request) -> AIProviderConfiguration:
    metadata, owns_metadata = await _setup_metadata(request)
    secret_store = getattr(request.app.state, "ai_secret_store", LocalEnvAIProviderSecretStore())
    try:
        # Any provider/model change invalidates previously validated readiness before
        # persisting or testing the replacement configuration.
        await metadata.update_setup_facts(ai_provider_ready=False)
        safe = AIProviderConfiguration(
            provider=payload.provider,
            model=payload.model,
            endpoint=payload.endpoint,
        )
        saved = await metadata.save_ai_provider_configuration(safe)
        if payload.api_key.strip():
            await secret_store.put_ai_provider_secret(
                payload.provider,
                AIProviderSecretInput(api_key=payload.api_key),
            )
        has_secret = await secret_store.has_ai_provider_secret(payload.provider)
        validator = getattr(request.app.state, "ai_provider_validator", None)
        validated = False
        if has_secret and validator is not None:
            try:
                await validator.validate(saved)
                validated = True
            except Exception as exc:
                await metadata.update_setup_facts(ai_provider_ready=False)
                raise HTTPException(status_code=422, detail="AI provider validation failed.") from exc
        await metadata.update_setup_facts(ai_provider_ready=validated)
        return saved.model_copy(update={"credential_configured": has_secret})
    finally:
        if owns_metadata:
            await metadata.close()


class SystemReadiness(BaseModel):
    ready: bool
    setup_ready: bool
    metadata_storage: str
    ai_provider: str
    data_source: str


@router.get("/readiness", response_model=SystemReadiness)
async def system_readiness(request: Request) -> SystemReadiness:
    """Report product readiness from persisted onboarding facts, not static env presence."""
    metadata, owns_metadata = await _setup_metadata(request)
    try:
        facts = await metadata.get_setup_facts()
        setup = derive_setup_status(**facts)
        return SystemReadiness(
            ready=setup.ready,
            setup_ready=setup.ready,
            metadata_storage="ready",
            ai_provider="ready" if facts["ai_provider_ready"] else "not_ready",
            data_source="ready" if facts["data_source_ready"] else "not_ready",
        )
    finally:
        if owns_metadata:
            await metadata.close()


@router.get("/status", response_model=SetupStatus)
async def setup_status(request: Request) -> SetupStatus:
    settings = request.app.state.settings
    if not settings.metadata_database_url:
        raise HTTPException(
            status_code=503,
            detail="Platform metadata storage is not configured.",
        )
    metadata = getattr(request.app.state, "setup_metadata", None)
    owns_metadata = metadata is None
    if metadata is None:
        metadata = PostgreSQLMetadataProvider(
            settings.metadata_database_url,
            pool_size=settings.metadata_database_pool_size,
        )
    try:
        facts = await metadata.get_setup_facts()
        return derive_setup_status(**facts)
    finally:
        if owns_metadata:
            await metadata.close()


class ConnectionTestResult(BaseModel):
    connected: bool


@router.post("/data-source/test", response_model=ConnectionTestResult)
async def test_data_source_connection(payload: PostgreSQLConnectionInput) -> ConnectionTestResult:
    """Validate customer PostgreSQL connectivity without persisting credentials or readiness."""
    try:
        connected = await test_postgresql_connection(payload)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="PostgreSQL connection failed. Check host, port, credentials, network and SSL settings.") from exc
    if not connected:
        raise HTTPException(status_code=422, detail="PostgreSQL connection failed. Check host, port, credentials, network and SSL settings.")
    return ConnectionTestResult(connected=True)


class SavedDataSource(BaseModel):
    id: int
    name: str
    connected: bool


@router.post("/data-source", response_model=SavedDataSource)
async def save_setup_data_source(payload: PostgreSQLConnectionInput, request: Request) -> SavedDataSource:
    """Validate, persist non-secret metadata and encrypted credential, then advance."""
    metadata, owns_metadata = await _setup_metadata(request)
    secret_store = getattr(request.app.state, "data_source_secret_store", None)
    if secret_store is None:
        secret_store = LocalDataSourceSecretStore()
    try:
        await metadata.update_setup_facts(data_source_ready=False, data_selection_ready=False, semantic_model_ready=False)
        try:
            connected = await test_postgresql_connection(payload)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="PostgreSQL connection failed. Check host, port, credentials, network and SSL settings.") from exc
        if not connected:
            raise HTTPException(status_code=422, detail="PostgreSQL connection failed. Check host, port, credentials, network and SSL settings.")
        source_id = await metadata.save_data_source(
            name=payload.name, provider="postgresql", host=payload.host,
            port=payload.port, database_name=payload.database,
            username=payload.username, sslmode=payload.sslmode,
        )
        try:
            secret_store.put(source_id, payload.password.get_secret_value())
            if secret_store.resolve_for_runtime(source_id) != payload.password.get_secret_value():
                raise RuntimeError("Credential verification failed")
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Unable to persist datasource credentials.") from exc
        await metadata.set_active_data_source_id(source_id)
        await metadata.update_setup_facts(data_source_ready=True)
        return SavedDataSource(id=source_id, name=payload.name, connected=True)
    finally:
        if owns_metadata:
            await metadata.close()



@router.get("/data-sources")
async def list_setup_data_sources(request: Request):
    metadata, owns_metadata = await _setup_metadata(request)
    try:
        return await metadata.list_saved_data_sources()
    finally:
        if owns_metadata:
            await metadata.close()


@router.post("/data-source/{source_id}/activate")
async def activate_setup_data_source(source_id: int, request: Request):
    """Activate only a stored, reachable connection with an available credential."""
    metadata, owns_metadata = await _setup_metadata(request)
    store = getattr(request.app.state, "data_source_secret_store", None) or LocalDataSourceSecretStore()
    provider = None
    try:
        try:
            provider = await open_saved_data_source(metadata, store, source_id)
            if not await provider.ping():
                raise ValueError("Connection unavailable")
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Saved datasource cannot be connected. Reconfigure its credentials if needed.") from exc
        await metadata.set_active_data_source_id(source_id)
        await metadata.update_setup_facts(data_source_ready=True, data_selection_ready=False, semantic_model_ready=False)
        record = await metadata.get_data_source(source_id)
        return {"id": record["id"], "name": record["name"], "provider": record["provider"]}
    finally:
        if provider is not None:
            await provider.close()
        if owns_metadata:
            await metadata.close()


@router.get("/data-source/active")
async def active_setup_data_source(request: Request):
    """Return the selected non-secret datasource identity after restart."""
    metadata, owns_metadata = await _setup_metadata(request)
    try:
        source_id = await metadata.get_active_data_source_id()
        if source_id is None:
            raise HTTPException(status_code=404, detail="No active datasource selected.")
        record = await metadata.get_data_source(source_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Active datasource no longer exists.")
        return {"id": record["id"], "name": record["name"], "provider": record["provider"]}
    finally:
        if owns_metadata:
            await metadata.close()


class SavedDiscoveryResponse(BaseModel):
    data_source_id: int
    schemas: list[str]
    tables: int
    persisted: bool


@router.post("/data-source/{source_id}/discover", response_model=SavedDiscoveryResponse)
async def discover_saved_source(source_id: int, request: Request) -> SavedDiscoveryResponse:
    metadata, owns_metadata = await _setup_metadata(request)
    store = getattr(request.app.state, "data_source_secret_store", None) or LocalDataSourceSecretStore()
    provider = None
    stage = "connection"
    try:
        try:
            provider = await open_saved_data_source(metadata, store, source_id)
            stage = "schema_listing"
            names = await provider.list_schemas()
            stage = "schema_introspection"
            schemas = [await provider.introspect_schema(name) for name in names]
            stage = "metadata_persistence"
            for schema in schemas:
                await metadata.save_schema(schema, data_source_id=source_id)
            return SavedDiscoveryResponse(
                data_source_id=source_id,
                schemas=names,
                tables=sum(len(schema.tables) for schema in schemas),
                persisted=True,
            )
        except Exception as exc:
            # Never log exception messages: drivers can include connection details.
            _logger.error("Saved datasource discovery failed: stage=%s error_type=%s", stage, type(exc).__name__)
            raise HTTPException(status_code=422, detail="Saved datasource discovery failed at " + stage + ".") from exc
    finally:
        if provider is not None:
            await provider.close()
        if owns_metadata:
            await metadata.close()
