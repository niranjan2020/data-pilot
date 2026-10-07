"""Health and system inspection endpoints."""

from typing import Any, Dict
from fastapi import APIRouter, Depends, Request
from datapilot.application.services.health import HealthReport, HealthService
from datapilot.core.config import Settings, get_settings

router = APIRouter(tags=["Health & System"])


def get_health_service(request: Request, settings: Settings = Depends(get_settings)) -> HealthService:
    """Dependency provider for HealthService using composed runtime probes when available."""
    return HealthService(settings=settings, runtime_checker=getattr(request.app.state, "runtime_health_checker", None))


@router.get(
    "/health",
    summary="Liveness Probe",
    description="Returns a lightweight status indicating that the application process is running.",
)
async def health(health_service: HealthService = Depends(get_health_service)) -> Dict[str, Any]:
    return health_service.get_liveness()


@router.get(
    "/health/ready",
    response_model=HealthReport,
    summary="Readiness Probe",
    description=(
        "Reports health of runtime infrastructure through composed live health checks. "
        "This endpoint is intentionally separate from onboarding readiness at /api/setup/readiness."
    ),
)
async def readiness(health_service: HealthService = Depends(get_health_service)) -> HealthReport:
    return await health_service.get_readiness()


@router.get(
    "/info",
    summary="System Information",
    description="Returns architectural metadata and supported capabilities of the open-source core.",
)
async def info(settings: Settings = Depends(get_settings)) -> Dict[str, Any]:
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "supported_database_dialects": [
            "postgresql",
            "mysql",
            "sqlserver",
            "snowflake",
            "bigquery",
        ],
        "supported_llm_providers": [
            "gemini",
            "openai",
            "anthropic",
            "local",
        ],
        "architecture": {
            "type": "modular_monolith",
            "edition": "open-source-core",
            "db_agnostic": True,
            "llm_agnostic": True,
        },
    }
