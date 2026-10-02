"""Application entry point for running the Data Pilot API server."""

import uvicorn
from datapilot.core.config import get_settings


def run() -> None:
    """Start the Data Pilot FastAPI application server."""
    settings = get_settings()
    uvicorn.run(
        "datapilot.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
