"""Concrete runtime health checks for locally composed infrastructure."""

from __future__ import annotations

from datapilot.domain.interfaces.runtime_health import RuntimeComponentHealth
from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider


class LocalRuntimeHealthChecker:
    """Check infrastructure owned by the Data Pilot runtime, not onboarding targets."""

    def __init__(self, metadata: PostgreSQLMetadataProvider | None) -> None:
        self._metadata = metadata

    async def check(self) -> dict[str, RuntimeComponentHealth]:
        if self._metadata is None:
            return {
                "metadata": RuntimeComponentHealth(
                    status="degraded",
                    details={"reachable": False, "reason": "metadata_not_configured"},
                )
            }
        try:
            await self._metadata.initialize()
            return {
                "metadata": RuntimeComponentHealth(
                    status="healthy",
                    details={"reachable": True},
                )
            }
        except Exception as exc:
            return {
                "metadata": RuntimeComponentHealth(
                    status="unhealthy",
                    details={"reachable": False, "error_type": type(exc).__name__},
                )
            }
