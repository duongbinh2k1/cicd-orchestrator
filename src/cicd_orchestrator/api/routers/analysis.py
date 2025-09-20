"""Analysis status and management endpoints."""

from datetime import datetime
from typing import Any, Dict, Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from ...core.database import get_database_session
from ...models.orchestrator import OrchestrationResponse
from ...services.orchestration_service import OrchestrationService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/analysis", tags=["📊 Analysis Management"])


class AnalysisSummary(BaseModel):
    """Summary of an analysis request."""
    request_id: str
    status: str
    project_id: int
    pipeline_id: Optional[int] = None
    job_id: Optional[int] = None
    created_at: str
    processing_time_ms: Optional[float] = None
    ai_provider: Optional[str] = None
    error_message: Optional[str] = None


class ActiveAnalysesResponse(BaseModel):
    """Response for active analyses list."""
    active_analyses: int = Field(description="Number of currently active analyses")
    total_found: int = Field(description="Total analyses found")
    analyses: List[AnalysisSummary] = Field(description="List of analysis summaries")


class AnalysisStatsResponse(BaseModel):
    """Analysis statistics response."""
    total_analyses: int
    success_rate: float
    average_processing_time_ms: float
    ai_provider_usage: Dict[str, int]
    recent_activity: Dict[str, Any]


async def get_orchestration_service(
    db: AsyncSession = Depends(get_database_session)
) -> OrchestrationService:
    """Get orchestration service dependency."""
    return OrchestrationService(db)


@router.get("/{request_id}",
            response_model=OrchestrationResponse,
            summary="🔍 Get Analysis Status", 
            description="""
**Get the status and results of a specific analysis request.**

Retrieves detailed information about an analysis:
- 📊 Current processing status
- 🤖 AI analysis results and recommendations
- ⏱️ Processing timeline and performance
- 🔗 Related GitLab project and pipeline info
- ❌ Error details if analysis failed

**Status Values:**
- `pending` - Analysis queued for processing
- `processing` - Currently being analyzed
- `completed` - Analysis finished successfully
- `failed` - Analysis encountered an error
            """,
            responses={
                200: {
                    "description": "Analysis found and details returned",
                    "content": {
                        "application/json": {
                            "example": {
                                "request_id": "webhook_1695128400000",
                                "status": "completed",
                                "project_id": 1001,
                                "pipeline_id": 123456,
                                "created_at": "2025-09-19T13:57:00.000Z",
                                "ai_analysis": {
                                    "summary": "Build failed due to missing Node.js dependencies",
                                    "root_cause": "npm install failed - package.json missing dependencies",
                                    "recommendations": ["Add missing dependencies to package.json"]
                                }
                            }
                        }
                    }
                },
                404: {
                    "description": "Analysis not found",
                    "content": {
                        "application/json": {
                            "example": {
                                "detail": "Analysis with request_id 'invalid_id' not found"
                            }
                        }
                    }
                }
            })
async def get_analysis_status(
    request_id: str = Path(..., description="Analysis request ID"),
    orchestration_service: OrchestrationService = Depends(get_orchestration_service),
) -> OrchestrationResponse:
    """Get analysis status by request ID.
    
    Args:
        request_id: Analysis request ID
        orchestration_service: Orchestration service dependency
        
    Returns:
        Analysis status and results
        
    Raises:
        HTTPException: When analysis not found
    """
    analysis = await orchestration_service.get_analysis_status(request_id)
    
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis with request_id '{request_id}' not found"
        )
    
    return analysis


@router.get("/",
            response_model=ActiveAnalysesResponse,
            summary="📋 List Active Analyses",
            description="""
**List all currently active and recent analysis requests.**

Provides overview of:
- 🔄 Currently processing analyses
- ✅ Recently completed analyses
- ❌ Failed analyses with error details
- 📈 Processing performance metrics

**Filtering Options:**
- Limit results with `limit` parameter
- Filter by status with `status` parameter
- Filter by project with `project_id` parameter

Perfect for:
- Monitoring analysis progress
- Debugging processing issues
- Performance analysis
            """,
            responses={
                200: {
                    "description": "List of analyses",
                    "content": {
                        "application/json": {
                            "example": {
                                "active_analyses": 2,
                                "total_found": 5,
                                "analyses": [
                                    {
                                        "request_id": "webhook_1695128400000",
                                        "status": "processing",
                                        "project_id": 1001,
                                        "pipeline_id": 123456,
                                        "created_at": "2025-09-19T13:57:00.000Z",
                                        "ai_provider": "openai"
                                    }
                                ]
                            }
                        }
                    }
                }
            })
async def list_active_analyses(
    limit: int = Query(50, ge=1, le=100, description="Maximum number of analyses to return"),
    status: Optional[str] = Query(None, description="Filter by analysis status"),
    project_id: Optional[int] = Query(None, description="Filter by GitLab project ID"),
    orchestration_service: OrchestrationService = Depends(get_orchestration_service),
) -> ActiveAnalysesResponse:
    """List all active analyses.
    
    Args:
        orchestration_service: Orchestration service dependency
        
    Returns:
        List of active analyses
    """
    active_analyses = await orchestration_service.list_active_analyses()
    
    # Convert to AnalysisSummary objects
    summaries = []
    for analysis in active_analyses:
        try:
            summary = AnalysisSummary(
                request_id=analysis.request_id,
                status=analysis.status.value,  # Convert enum to string
                project_id=analysis.project_id,
                pipeline_id=getattr(analysis, 'pipeline_id', None),
                job_id=None,  # Not tracked currently
                created_at=str(analysis.created_at),
                processing_time_ms=analysis.total_processing_time_ms,
                ai_provider=analysis.ai_analysis.provider if analysis.ai_analysis else None,
                error_message=analysis.error_message
            )
            summaries.append(summary)
        except Exception as e:
            logger.error("Failed to convert analysis to summary", error=str(e))
            continue
    
    return ActiveAnalysesResponse(
        active_analyses=len(active_analyses),
        total_found=len(summaries),
        analyses=summaries
    )


@router.get("/stats/summary",
            response_model=Dict[str, Any],
            summary="Analysis Statistics",
            description="Get summary statistics about analysis performance.")
async def get_analysis_stats() -> Dict[str, Any]:
    """Get analysis statistics.
    
    Returns:
        Analysis statistics and metrics
    """
    # TODO: Implement statistics collection from database
    return {
        "message": "Statistics collection not yet implemented",
        "total_analyses": 0,
        "success_rate": 0.0,
        "average_processing_time_ms": 0.0,
        "ai_provider_usage": {},
    }
