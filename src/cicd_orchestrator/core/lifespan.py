"""Application lifecycle management."""

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
import structlog

from .config import settings
from .database import init_database, close_database, get_database_session
from ..services.orchestration_service import OrchestrationService

logger = structlog.get_logger(__name__)

# Global service instances
orchestration_service: Optional[OrchestrationService] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global orchestration_service
    
    # Startup
    logger.info(
        "🚀 Starting CI/CD Orchestrator",
        version=settings.app_version,
        environment=settings.environment,
        debug=settings.debug,
        port=settings.port,
        trigger_mode=settings.trigger_mode,
    )
    
    # Initialize database
    db_success = await init_database()
    if not db_success:
        logger.warning("Application starting without database connection")
        
    # Initialize orchestration service as the main brain
    db = await anext(get_database_session())
    orchestration_service = OrchestrationService(db)
    
    # Start email monitoring if configured - orchestrator controls this
    if settings.trigger_mode in ["email", "both"] and settings.imap_enabled:
        try:
            logger.info(
                "Starting orchestrator-controlled email monitoring",
                trigger_mode=settings.trigger_mode,
                imap_enabled=settings.imap_enabled
            )
            # Orchestrator manages email monitoring directly
            await orchestration_service.start_email_monitoring()
            logger.info("Orchestrator email monitoring started")
        except Exception as e:
            logger.error(
                "Failed to start orchestrator email monitoring",
                error=str(e)
            )
    else:
        logger.info(
            "Email monitoring disabled",
            trigger_mode=settings.trigger_mode,
            imap_enabled=settings.imap_enabled
        )
    
    logger.info("✅ Orchestrator startup completed - brain is online")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down CI/CD Orchestrator")
    
    # Stop orchestrator email monitoring if running
    if orchestration_service:
        await orchestration_service.stop_email_monitoring()
        logger.info("Orchestrator email monitoring stopped")
    
    # Close database connections
    await close_database()
    logger.info("✅ Orchestrator shutdown completed")
