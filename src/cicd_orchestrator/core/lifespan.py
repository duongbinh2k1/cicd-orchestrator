"""Application lifecycle management."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
import structlog

from .config import settings
from .database import init_database, close_database

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info(
        "🚀 Starting CI/CD Orchestrator",
        version=settings.app_version,
        environment=settings.environment,
        debug=settings.debug,
        port=settings.port,
    )
    
    # Initialize database
    db_success = await init_database()
    if not db_success:
        logger.warning("Application starting without database connection")
    
    logger.info("✅ Application startup completed")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down CI/CD Orchestrator")
    await close_database()
    logger.info("✅ Application shutdown completed")
