"""Health service in the application layer.

Assesses liveness and readiness of the Data Pilot core engine and registered providers.
"""

from datetime import datetime, timezone
import platform
import sys
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from datapilot.core.config import Settings, get_settings
from datapilot.domain.interfaces.runtime_health import RuntimeHealthChecker


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

    def __init__(self, settings: Optional[Settings] = None, runtime_checker: Optional[RuntimeHealthChecker] = None):
        self._settings = settings or get_settings()
        self._runtime_checker = runtime_checker
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
        """Report runtime infrastructure health independently from onboarding state."""
        components: Dict[str, ComponentStatus] = {}
        if self._runtime_checker is not None:
            checked = await self._runtime_checker.check()
            components = {
                name: ComponentStatus(status=value.status, details=value.details)
                for name, value in checked.items()
            }

        statuses = {component.status for component in components.values()}
        overall_status = "unhealthy" if "unhealthy" in statuses else ("degraded" if "degraded" in statuses else "healthy")

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
