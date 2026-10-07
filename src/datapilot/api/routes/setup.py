"""First-run onboarding status API."""

from fastapi import APIRouter, HTTPException, Request

from datapilot.application.setup_state import SetupStatus, derive_setup_status
from datapilot.core.config import get_settings
from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider

router = APIRouter(prefix="/api/setup", tags=["Setup"])


@router.get("/status", response_model=SetupStatus)
async def setup_status(request: Request) -> SetupStatus:
    settings = get_settings()
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
