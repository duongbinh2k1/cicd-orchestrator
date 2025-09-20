"""GitLab webhook endpoint handlers."""

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status, Body
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from ...core.config import settings
from ...core.database import get_database_session
from ...core.exceptions import WebhookValidationError, OrchestrationError
from ...models.gitlab import GitLabWebhook, GitLabEventType
from ...models.orchestrator import OrchestrationRequest, OrchestrationResponse
from ...services.orchestration_service import OrchestrationService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookTestRequest(BaseModel):
    """Request model for testing webhooks."""
    webhook_data: Dict[str, Any] = Field(
        ...,
        description="GitLab webhook payload",
        example={
            "object_kind": "pipeline",
            "object_attributes": {
                "id": 123456,
                "status": "failed",
                "ref": "main",
                "tag": False,
                "sha": "abc123def456",
                "before_sha": "000000000000",
                "source": "push",
                "created_at": "2025-09-19T13:00:00.000Z",
                "finished_at": "2025-09-19T13:05:00.000Z",
                "duration": 300,
                "stages": ["build", "test", "deploy"],
                "detailed_status": "failed"
            },
            "project": {
                "id": 1001,
                "name": "example-project", 
                "description": "Example project for testing",
                "web_url": "https://gitlab.com/group/example-project",
                "avatar_url": None,
                "namespace": "group",
                "path_with_namespace": "group/example-project",
                "default_branch": "main"
            },
            "user": {
                "id": 1,
                "name": "Developer",
                "username": "dev",
                "email": "dev@example.com"
            },
            "commit": {
                "id": "abc123def456",
                "message": "Fix build configuration",
                "timestamp": "2025-09-19T12:55:00.000Z",
                "url": "https://gitlab.com/group/example-project/-/commit/abc123def456",
                "author": {
                    "name": "Developer",
                    "email": "dev@example.com"
                }
            }
        }
    )
    simulate_signature: bool = Field(
        False,
        description="Whether to simulate signature verification (for testing)"
    )
security = HTTPBearer(auto_error=False)


def verify_gitlab_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitLab webhook signature.
    
    Args:
        payload: Raw request payload
        signature: X-Gitlab-Token header value
        secret: Webhook secret
        
    Returns:
        True if signature is valid
    """
    if not secret:
        return True  # No secret configured, skip verification
    
    return hmac.compare_digest(signature, secret)


def verify_gitlab_hmac_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitLab webhook HMAC signature.
    
    Args:
        payload: Raw request payload
        signature: X-Gitlab-Event-UUID or signature header
        secret: Webhook secret
        
    Returns:
        True if signature is valid
    """
    if not secret or not signature:
        return True  # No secret configured, skip verification
    
    expected_signature = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected_signature)


async def get_orchestration_service(
    db: AsyncSession = Depends(get_database_session)
) -> OrchestrationService:
    """Get orchestration service dependency."""
    return OrchestrationService(db)


@router.post("/gitlab", 
             response_model=Dict[str, Any],
             status_code=status.HTTP_202_ACCEPTED,
             summary="🔗 GitLab Webhook Handler",
             description="""
**Receives GitLab webhooks for CI/CD pipeline events and triggers error analysis.**

This endpoint processes webhooks from GitLab when CI/CD events occur:
- ✅ Validates webhook signature (if secret configured)
- 🔍 Analyzes failed/canceled pipelines and jobs
- 🚀 Triggers background processing for error analysis
- 📊 Returns processing status and request tracking

**Supported Events:**
- `Pipeline Hook` - Pipeline failed/canceled
- `Job Hook` - Job failed/canceled

**Required Headers:**
- `X-Gitlab-Event`: Event type (Pipeline Hook or Job Hook)
- `X-Gitlab-Event-UUID`: Unique event identifier
- `X-Gitlab-Token`: Webhook secret (if configured)
             """,
             responses={
                 202: {
                     "description": "Webhook accepted for processing",
                     "content": {
                         "application/json": {
                             "example": {
                                 "status": "accepted",
                                 "message": "Webhook received and analysis started",
                                 "request_id": "webhook_1695128400000",
                                 "gitlab_event_uuid": "abc-123-def",
                                 "project_id": 1001,
                                 "pipeline_id": 123456,
                                 "processing_time_ms": 45.2
                             }
                         }
                     }
                 },
                 400: {"description": "Invalid JSON payload"},
                 401: {"description": "Invalid webhook signature"},
                 422: {"description": "Invalid webhook payload structure"}
             })
async def gitlab_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    orchestration_service: OrchestrationService = Depends(get_orchestration_service),
) -> Dict[str, Any]:
    """Handle GitLab webhook events.
    
    This endpoint receives webhooks from GitLab when CI/CD events occur,
    validates the payload, and triggers error analysis for failed jobs.
    
    Args:
        request: FastAPI request object
        background_tasks: FastAPI background tasks
        orchestration_service: Orchestration service dependency
        
    Returns:
        Response indicating webhook was received and processing status
        
    Raises:
        HTTPException: For invalid webhooks or processing errors
    """
    request_id = f"webhook_{int(datetime.utcnow().timestamp() * 1000)}"
    start_time = datetime.utcnow()
    
    logger.info(
        "Received GitLab webhook",
        request_id=request_id,
        headers=dict(request.headers),
        client_ip=request.client.host if request.client else None,
    )
    
    try:
        # Get raw payload for signature verification
        payload = await request.body()
        
        # Get headers
        gitlab_event = request.headers.get("X-Gitlab-Event")
        gitlab_token = request.headers.get("X-Gitlab-Token")
        gitlab_uuid = request.headers.get("X-Gitlab-Event-UUID")
        
        logger.info(
            "GitLab webhook headers",
            request_id=request_id,
            gitlab_event=gitlab_event,
            gitlab_uuid=gitlab_uuid,
            has_token=bool(gitlab_token),
        )
        
        # Verify webhook signature if secret is configured
        if settings.gitlab_webhook_secret:
            if not gitlab_token:
                logger.warning("Missing GitLab token", request_id=request_id)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing X-Gitlab-Token header"
                )
            
            if not verify_gitlab_signature(payload, gitlab_token, settings.gitlab_webhook_secret):
                logger.warning("Invalid GitLab webhook signature", request_id=request_id)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid webhook signature"
                )
        
        # Parse JSON payload
        try:
            webhook_data = json.loads(payload.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON payload", request_id=request_id, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON payload: {e}"
            )
        
        # Validate webhook event type
        if gitlab_event not in [GitLabEventType.PIPELINE, GitLabEventType.JOB]:
            logger.info(
                "Skipping non-pipeline/job webhook",
                request_id=request_id,
                event_type=gitlab_event,
            )
            return {
                "status": "ignored",
                "message": "Event type not processed",
                "event_type": gitlab_event,
                "request_id": request_id,
            }
        
        # Validate and parse webhook payload
        try:
            gitlab_webhook = GitLabWebhook(**webhook_data)
        except Exception as e:
            logger.error("Invalid webhook payload", request_id=request_id, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid webhook payload: {e}"
            )
        
        # Check if this is a failure event that requires analysis
        should_analyze = False
        failure_reason = None
        
        if gitlab_event == GitLabEventType.PIPELINE:
            if gitlab_webhook.object_attributes.status in ["failed", "canceled"]:
                should_analyze = True
                failure_reason = f"Pipeline {gitlab_webhook.object_attributes.status}"
        
        elif gitlab_event == GitLabEventType.JOB:
            if gitlab_webhook.object_attributes.status in ["failed", "canceled"]:
                should_analyze = True
                failure_reason = gitlab_webhook.object_attributes.failure_reason or "Job failed"
        
        if not should_analyze:
            logger.info(
                "Webhook event does not require analysis",
                request_id=request_id,
                event_type=gitlab_event,
                status=gitlab_webhook.object_attributes.status,
            )
            return {
                "status": "ignored",
                "message": "Event does not require analysis",
                "event_type": gitlab_event,
                "status": gitlab_webhook.object_attributes.status,
                "request_id": request_id,
            }
        
        # Create orchestration request
        orchestration_request = OrchestrationRequest(
            webhook_data=gitlab_webhook,
            priority=7 if gitlab_webhook.object_attributes.status == "failed" else 5,
            include_context=True,
            include_repository_files=False,  # Disable by default for performance
        )

        # Process immediately - simple webhook processing
        logger.info(
            "Processing CI/CD webhook directly",
            request_id=request_id,
            project_id=gitlab_webhook.project.id,
            pipeline_id=gitlab_webhook.object_attributes.id,
            failure_reason=failure_reason,
        )
        
        # Use background task with async wrapper for processing
        try:
            async def run_async_analysis():
                try:
                    await orchestration_service.process_webhook(
                        orchestration_request,
                        request_id,
                    )
                    logger.info(
                        "Background analysis completed successfully",
                        request_id=request_id,
                        project_id=gitlab_webhook.project.id
                    )
                except Exception as analysis_error:
                    logger.error(
                        "Background analysis failed",
                        request_id=request_id,
                        error=str(analysis_error)
                    )

            # Add the wrapped async task
            background_tasks.add_task(run_async_analysis)
            logger.info("Background analysis task scheduled", request_id=request_id)
        except Exception as e:
            logger.error(
                "Failed to schedule background task",
                request_id=request_id,
                error=str(e)
            )
            return {
                "status": "error", 
                "request_id": request_id,
                "message": "Failed to schedule analysis task"
            }
        
        processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        logger.info(
            "GitLab webhook processed successfully",
            request_id=request_id,
            processing_time_ms=processing_time,
            project_id=gitlab_webhook.project.id,
        )
        
        return {
            "status": "ok",
            "request_id": request_id,
        }
        
    except HTTPException:
        raise
    except WebhookValidationError as e:
        logger.error("Webhook validation error", request_id=request_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Webhook validation error: {e}"
        )
    except Exception as e:
        logger.error("Unexpected error processing webhook", request_id=request_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error processing webhook"
        )


@router.post("/gitlab/test",
             response_model=Dict[str, Any],
             summary="🧪 Test GitLab Webhook",
             description="""
**Test endpoint for validating GitLab webhook configuration.**

This endpoint allows you to test webhook payloads without signature verification:
- 🔍 Validates webhook payload structure
- ✅ Checks if payload would trigger analysis
- 📝 Returns detailed validation results
- 🚫 No signature verification (safe for testing)

**Use Cases:**
- Validate webhook payload format
- Test webhook configuration 
- Debug webhook issues
- Development and testing
             """,
             responses={
                 200: {
                     "description": "Test results",
                     "content": {
                         "application/json": {
                             "example": {
                                 "status": "valid",
                                 "message": "Webhook payload is valid",
                                 "request_id": "test_1695128400000",
                                 "project_id": 1001,
                                 "event_type": "pipeline",
                                 "would_analyze": True,
                                 "analysis_trigger": "failed"
                             }
                         }
                     }
                 }
             })
async def test_gitlab_webhook(
    webhook_test: WebhookTestRequest,
    background_tasks: BackgroundTasks,
    orchestration_service: OrchestrationService = Depends(get_orchestration_service),
) -> Dict[str, Any]:
    """Test GitLab webhook processing without signature verification.
    
    This endpoint is useful for testing webhook payloads during development
    or for validating webhook configuration.
    
    Args:
        webhook_test: Webhook test request with payload and options
        orchestration_service: Orchestration service dependency
        
    Returns:
        Test results and validation status
    """
    request_id = f"test_{int(datetime.utcnow().timestamp() * 1000)}"
    
    logger.info("Testing GitLab webhook", request_id=request_id)
    
    try:
        # Validate webhook payload
        gitlab_webhook = GitLabWebhook(**webhook_test.webhook_data)
        
        # Check if this would trigger analysis
        should_analyze = False
        analysis_trigger = None
        if hasattr(gitlab_webhook.object_attributes, 'status'):
            status = gitlab_webhook.object_attributes.status
            if status in ["failed", "canceled"]:
                should_analyze = True
                analysis_trigger = status

        # If webhook_test requests actual analysis
        if should_analyze and webhook_test.simulate_signature:
            # Create orchestration request for test analysis
            orchestration_request = OrchestrationRequest(
                webhook_data=gitlab_webhook,
                priority=7 if analysis_trigger == "failed" else 5,
                include_context=True,
                include_repository_files=False
            )

            # Run test analysis in background
            async def run_async_test_analysis():
                try:
                    await orchestration_service.process_webhook(
                        orchestration_request,
                        request_id
                    )
                    logger.info(
                        "Test analysis completed successfully",
                        request_id=request_id,
                        project_id=gitlab_webhook.project.id
                    )
                except Exception as analysis_error:
                    logger.error(
                        "Test analysis failed",
                        request_id=request_id,
                        error=str(analysis_error)
                    )

            # Add background task
            background_tasks.add_task(run_async_test_analysis)
            logger.info("Test analysis task scheduled", request_id=request_id)

        return {
            "status": "valid",
            "message": "Webhook payload is valid",
            "request_id": request_id,
            "project_id": gitlab_webhook.project.id,
            "event_type": gitlab_webhook.object_kind,
            "would_analyze": should_analyze,
            "analysis_trigger": analysis_trigger,
            "test_analysis_started": should_analyze and webhook_test.simulate_signature
        }
        
    except Exception as e:
        logger.error("Webhook test failed", request_id=request_id, error=str(e))
        return {
            "status": "invalid",
            "message": f"Webhook validation failed: {e}",
            "request_id": request_id,
            "error": str(e),
        }


@router.get("/gitlab/info",
            response_model=Dict[str, Any],
            summary="ℹ️ GitLab Webhook Info",
            description="""
**Get information about GitLab webhook configuration.**

Returns comprehensive information about:
- 🔗 Webhook URL and endpoints
- 📋 Supported events and headers
- ⚙️ Configuration requirements
- 🔒 Security settings
- 📖 GitLab setup instructions

**Perfect for:**
- Setting up GitLab webhooks
- Troubleshooting configuration
- Understanding supported events
            """,
            responses={
                200: {
                    "description": "Webhook configuration information",
                    "content": {
                        "application/json": {
                            "example": {
                                "webhook_url": "/webhooks/gitlab",
                                "supported_events": ["Pipeline Hook", "Job Hook"],
                                "required_headers": ["X-Gitlab-Event", "X-Gitlab-Event-UUID"],
                                "webhook_secret_configured": False,
                                "gitlab_configuration": {
                                    "url": "http://localhost:8001/webhooks/gitlab",
                                    "events": ["Pipeline events", "Job events"],
                                    "enable_ssl_verification": True
                                }
                            }
                        }
                    }
                }
            })
async def gitlab_webhook_info() -> Dict[str, Any]:
    """Get GitLab webhook configuration information.
    
    Returns:
        Webhook configuration details and requirements
    """
    return {
        "webhook_url": "/webhooks/gitlab",
        "supported_events": [
            GitLabEventType.PIPELINE,
            GitLabEventType.JOB,
        ],
        "required_headers": [
            "X-Gitlab-Event",
            "X-Gitlab-Event-UUID",
        ],
        "optional_headers": [
            "X-Gitlab-Token",  # Required only if webhook secret is configured
        ],
        "webhook_secret_configured": bool(settings.gitlab_webhook_secret),
        "supported_trigger_events": [
            "Pipeline Hook - failed/canceled status",
            "Job Hook - failed/canceled status", 
        ],
        "gitlab_configuration": {
            "url": f"{settings.host}:{settings.port}/webhooks/gitlab",
            "events": ["Pipeline events", "Job events"],
            "enable_ssl_verification": True,
            "secret_token": "Configure GITLAB_WEBHOOK_SECRET environment variable",
        },
    }
