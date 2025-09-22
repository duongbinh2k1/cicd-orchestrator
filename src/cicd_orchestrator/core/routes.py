"""Router configuration and registration."""

from fastapi import FastAPI
import structlog

from ..api.routers import webhooks, health, analysis
from .config import settings

logger = structlog.get_logger(__name__)


def configure_routes(app: FastAPI) -> None:
    """Configure all routes for the application."""
    
    # Core routes (always available)
    app.include_router(health.router)
    app.include_router(webhooks.router)
    app.include_router(analysis.router)
    
    logger.info("Core routes configured", routes=["health", "webhooks", "analysis"])
    
    # Development routes (only in development)
    if settings.environment == "development":
        try:
            logger.info("Test endpoints loaded successfully")
        except Exception as e:
            logger.warning("Could not load test endpoints", error=str(e))
    else:
        logger.info("Test endpoints disabled in production environment")
