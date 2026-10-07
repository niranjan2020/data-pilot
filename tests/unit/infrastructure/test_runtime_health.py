import pytest

from datapilot.infrastructure.health import LocalRuntimeHealthChecker


class HealthyMetadata:
    async def initialize(self):
        return None


class FailingMetadata:
    async def initialize(self):
        raise RuntimeError("database unavailable")


@pytest.mark.asyncio
async def test_runtime_health_reports_metadata_reachable():
    result = await LocalRuntimeHealthChecker(HealthyMetadata()).check()
    assert result["metadata"].status == "healthy"
    assert result["metadata"].details == {"reachable": True}


@pytest.mark.asyncio
async def test_runtime_health_reports_metadata_failure_without_leaking_exception_message():
    result = await LocalRuntimeHealthChecker(FailingMetadata()).check()
    assert result["metadata"].status == "unhealthy"
    assert result["metadata"].details["reachable"] is False
    assert result["metadata"].details["error_type"] == "RuntimeError"
    assert "database unavailable" not in str(result["metadata"].details)


@pytest.mark.asyncio
async def test_runtime_health_reports_missing_metadata_as_degraded():
    result = await LocalRuntimeHealthChecker(None).check()
    assert result["metadata"].status == "degraded"
    assert result["metadata"].details["reason"] == "metadata_not_configured"
