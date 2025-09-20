"""Health check endpoints."""

from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, status, HTTPException
from pydantic import BaseModel
import structlog

from ...services.orchestration_service import OrchestrationService
from ...core.config import settings
from ...core.database import check_database_health

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/health", tags=["🏥 Health Monitoring"])


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    service: str
    timestamp: str
    version: str = settings.app_version
    environment: str = settings.environment


class DetailedHealthResponse(HealthResponse):
    """Detailed health check response model."""
    components: Dict[str, bool]
    details: Dict[str, Any]


class ReadinessResponse(HealthResponse):
    """Readiness check response model."""
    checks: Dict[str, bool]


async def get_orchestration_service() -> OrchestrationService:
    """Get orchestration service dependency."""
    return OrchestrationService()


@router.get("/", 
            response_model=HealthResponse,
            summary="💚 Basic Health Check",
            description="""
**Quick health check endpoint for load balancers and monitoring.**

Returns basic service status information:
- ✅ Service availability
- 🏷️ Service version and environment
- ⏰ Current timestamp
- 🚀 Simple up/down status

Perfect for:
- Load balancer health checks
- Basic monitoring
- Quick status verification
            """,
            responses={
                200: {
                    "description": "Service is healthy",
                    "content": {
                        "application/json": {
                            "example": {
                                "status": "healthy",
                                "service": "cicd-orchestrator",
                                "timestamp": "2025-09-19T13:57:00.000Z",
                                "version": "0.1.0",
                                "environment": "development"
                            }
                        }
                    }
                }
            })
async def health_check() -> HealthResponse:
    """Basic health check endpoint.
    
    Returns:
        Health status information
    """
    return HealthResponse(
        status="healthy",
        service="cicd-orchestrator",
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@router.get("/detailed",
            response_model=DetailedHealthResponse, 
            summary="🔍 Detailed Health Check",
            description="""
**Comprehensive health check including all service dependencies.**

Provides detailed status of:
- 🤖 AI service providers (OpenAI, Anthropic, Azure)
- 🦊 GitLab client connectivity
- 📊 Active analysis count
- ⚙️ Service configuration
- 🔗 Dependency health

**Status Levels:**
- `healthy` - All components working
- `degraded` - Some components down but service functional
- `unhealthy` - Critical components down
            """,
            responses={
                200: {
                    "description": "Detailed health information",
                    "content": {
                        "application/json": {
                            "example": {
                                "status": "healthy",
                                "service": "cicd-orchestrator",
                                "timestamp": "2025-09-19T13:57:00.000Z",
                                "version": "0.1.0",
                                "environment": "development",
                                "components": {
                                    "ai_openai": True,
                                    "ai_anthropic": True,
                                    "gitlab_client": True
                                },
                                "details": {
                                    "active_analyses": 0,
                                    "available_ai_providers": 2
                                }
                            }
                        }
                    }
                }
            })
async def detailed_health_check(
    orchestration_service: OrchestrationService = Depends(get_orchestration_service),
) -> DetailedHealthResponse:
    """Detailed health check with dependency status.
    
    Args:
        orchestration_service: Orchestration service dependency
        
    Returns:
        Detailed health status of all components
    """
    try:
        # Get health status from orchestration service
        health_status = await orchestration_service.health_check()
        
        # Check database health
        db_health = await check_database_health()
        health_status["database"] = db_health["status"] == "healthy"
        
        # Determine overall health
        all_healthy = all(health_status.values())
        overall_status = "healthy" if all_healthy else "degraded"
        
        return {
            "status": overall_status,
            "service": "cicd-orchestrator",
            "timestamp": datetime.now().isoformat() + "Z",
            "components": health_status,
            "details": {
                "active_analyses": len(await orchestration_service.list_active_analyses()),
                "available_ai_providers": len(orchestration_service.ai_service.get_available_providers()),
                "database": db_health
            }
        }
        
    except Exception as e:
        logger.error("Health check failed", error=str(e))
        return {
            "status": "unhealthy", 
            "service": "cicd-orchestrator",
            "timestamp": datetime.now().isoformat() + "Z",
            "components": {},
            "details": {"error": str(e)}
        }


@router.get("/readiness",
            response_model=Dict[str, Any],
            summary="Readiness Check", 
            description="Kubernetes readiness probe endpoint.")
async def readiness_check(
    orchestration_service: OrchestrationService = Depends(get_orchestration_service),
) -> Dict[str, Any]:
    """Readiness check for Kubernetes.
    
    Args:
        orchestration_service: Orchestration service dependency
        
    Returns:
        Readiness status
    """
    try:
        # Check if critical dependencies are available
        health_status = await orchestration_service.health_check()
        
        # Service is ready if orchestration service and at least one AI provider is healthy
        ai_providers_healthy = any([
            health_status.get(f"ai_{provider}", False) 
            for provider in ["openai", "anthropic", "azure_openai"]
        ])
        
        gitlab_healthy = health_status.get("gitlab_client", False)
        
        is_ready = ai_providers_healthy and gitlab_healthy
        
        return {
            "status": "ready" if is_ready else "not_ready",
            "service": "cicd-orchestrator",
            "timestamp": "2024-01-01T00:00:00Z",
            "checks": {
                "ai_providers": ai_providers_healthy,
                "gitlab_client": gitlab_healthy,
            }
        }
        
    except Exception as e:
        logger.error("Readiness check failed", error=str(e))
        return {
            "status": "not_ready",
            "service": "cicd-orchestrator", 
            "timestamp": "2024-01-01T00:00:00Z",
            "error": str(e),
        }


@router.get("/liveness",
            response_model=Dict[str, Any],
            summary="Liveness Check",
            description="Kubernetes liveness probe endpoint.")
async def liveness_check() -> Dict[str, Any]:
    """Liveness check for Kubernetes.
    
    Returns:
        Liveness status
    """
    # Simple liveness check - just verify the application is running
    return {
        "status": "alive",
        "service": "cicd-orchestrator",
        "timestamp": "2024-01-01T00:00:00Z",
    }
