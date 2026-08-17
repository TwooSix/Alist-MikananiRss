"""
FastAPI application factory with lifespan management.
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Response, status

from openlist_ani.logger import logger
from .router import router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifespan — startup and shutdown hooks."""
    logger.debug("Backend API server starting up")
    yield
    logger.debug("Backend API server shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI instance.
    """
    app = FastAPI(
        title="OpenList-Ani Backend",
        description="Internal API for anime download and RSS management",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.include_router(router)

    @app.get("/health/live")
    async def health_live() -> dict[str, object]:
        return {"status": "live"}

    @app.get("/health/ready")
    async def health_ready(response: Response) -> dict[str, object]:
        from .service import BackendApiService

        try:
            result = BackendApiService.get().health()
        except RuntimeError:
            result = {"status": "starting", "ready": False}
        if not result.get("ready"):
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return result

    return app
