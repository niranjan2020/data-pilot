"""Health and system inspection endpoints."""

from typing import Any, Dict
from fastapi import APIRouter, Depends
from datapilot.application.services.health import HealthReport, HealthService
from datapilot.core.config import Settings, get_settings

router = APIRouter(tags=["Health & System"])


def get_health_service(settings: Settings = Depends(get_settings)) -> HealthService:
    """Dependency provider for HealthService."""
    return HealthService(settings=settings)


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
        "Provides readiness status based on loaded application configuration and runtime environment. "
        "Note: In Phase 1 foundation, 'configured' status indicates configuration presence only and "
        "does not imply that live remote database or LLM network connectivity has been verified."
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
