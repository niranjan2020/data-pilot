"""First-run onboarding status API."""

from fastapi import APIRouter, HTTPException, Request

from datapilot.application.setup_state import SetupStatus, derive_setup_status
from datapilot.domain.interfaces.ai_configuration import (
    AIProviderConfiguration,
    AIProviderKind,
    AIProviderSecretInput,
)
from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider
from datapilot.infrastructure.secrets.local_env import LocalEnvAIProviderSecretStore

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
