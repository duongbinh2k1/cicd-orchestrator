"""Main FastAPI application entry point."""

from typing import Any, Dict

from fastapi import FastAPI
import structlog

from .core.config import settings
from .core.logging import setup_logging
from .core.lifespan import lifespan
from .core.middleware import configure_middleware
from .core.handlers import configure_exception_handlers
from .core.routes import configure_routes

# Setup logging
setup_logging()
logger = structlog.get_logger(__name__)


# Create FastAPI application
app = FastAPI(
    title="CI/CD Orchestrator",
    description="🤖 Intelligent CI/CD pipeline failure analysis using AI",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.environment == "development" or settings.debug else None,
    redoc_url="/redoc" if settings.environment == "development" or settings.debug else None,
    contact={
        "name": "CI/CD Orchestrator",
        "email": "support@cicd-orchestrator.com",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
)

# Configure application components
configure_middleware(app)
configure_exception_handlers(app)
configure_routes(app)


@app.get("/", response_model=Dict[str, Any])
async def root() -> Dict[str, Any]:
    """🏠 Root endpoint with service information."""
    return {
        "service": "CI/CD Orchestrator",
        "description": "🤖 Intelligent CI/CD pipeline failure analysis using AI",
        "version": settings.app_version,
        "environment": settings.environment,
        "status": "running",
        "endpoints": {
            "health": "/health",
            "detailed_health": "/health/detailed",
            "webhooks": "/webhooks/gitlab",
            "analysis": "/analysis",
            "docs": "/docs" if settings.debug else "disabled",
            "test": "/test" if settings.environment == "development" else "disabled"
        },
        "features": {
            "gitlab_integration": True,
            "ai_analysis": True,
            "webhook_processing": True,
            "test_scenarios": settings.environment == "development",
            "database_connection": True
        },
        "quick_start": {
            "health_check": "GET /health/",
            "webhook_test": "POST /test/scenarios/failed_build" if settings.environment == "development" else "disabled",
            "documentation": "/docs" if settings.debug else "disabled"
        }
    }


if __name__ == "__main__":
    import uvicorn
    
    logger.info(
        "🚀 Starting CI/CD Orchestrator from main",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
    
    uvicorn.run(
        "cicd_orchestrator.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
