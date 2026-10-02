"""Health service in the application layer.

Assesses liveness and readiness of the Data Pilot core engine and registered providers.
"""

from datetime import datetime, timezone
import platform
import sys
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from datapilot.core.config import Settings, get_settings


class ComponentStatus(BaseModel):
    """Status details for an individual subsystem or provider."""

    status: str = Field(description="'healthy', 'degraded', 'unconfigured', or 'unhealthy'")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Diagnostic details")


class HealthReport(BaseModel):
    """Comprehensive health and readiness report."""

    status: str = Field(description="Overall service status: 'healthy', 'degraded', or 'unhealthy'")
    app: str = Field(description="Application name")
    version: str = Field(description="Semantic version")
    environment: str = Field(description="Runtime environment")
    timestamp: datetime = Field(description="ISO UTC timestamp of the health check")
    system: Dict[str, Any] = Field(description="Python runtime and OS diagnostics")
    components: Dict[str, ComponentStatus] = Field(default_factory=dict, description="Subsystem readiness")


class HealthService:
    """Application service for monitoring platform health and readiness."""

    def __init__(self, settings: Optional[Settings] = None):
        self._settings = settings or get_settings()
        self._start_time = datetime.now(timezone.utc)

    def get_liveness(self) -> Dict[str, Any]:
        """Simple, fast check verifying that the HTTP server process is running."""
        return {
            "status": "ok",
            "app": self._settings.app_name,
            "version": self._settings.app_version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def get_readiness(self) -> HealthReport:
        """Detailed readiness check assessing configuration, providers, and environment."""
        components: Dict[str, ComponentStatus] = {}

        # Check Database configuration status
        if self._settings.default_database_url:
            components["database"] = ComponentStatus(
                status="configured",
                details={"configured": True},
            )
        else:
            components["database"] = ComponentStatus(
                status="unconfigured",
                details={"message": "No default database URL configured in environment"},
            )

        # Check LLM provider configuration status
        components["llm"] = ComponentStatus(
            status="configured" if (
                self._settings.gemini_api_key
                or self._settings.openai_api_key
                or self._settings.anthropic_api_key
            ) else "unconfigured",
            details={
                "provider": self._settings.default_llm_provider,
                "has_gemini_key": bool(self._settings.gemini_api_key),
                "has_openai_key": bool(self._settings.openai_api_key),
                "has_anthropic_key": bool(self._settings.anthropic_api_key),
            },
        )

        # Core engine is healthy if configuration loaded properly
        overall_status = "healthy"

        return HealthReport(
            status=overall_status,
            app=self._settings.app_name,
            version=self._settings.app_version,
            environment=self._settings.environment,
            timestamp=datetime.now(timezone.utc),
            system={
                "python_version": sys.version.split()[0],
                "platform": platform.platform(),
                "uptime_seconds": (datetime.now(timezone.utc) - self._start_time).total_seconds(),
            },
            components=components,
        )
