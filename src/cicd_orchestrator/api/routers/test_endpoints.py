"""🧪 Test endpoints for simulating GitLab webhooks and CI/CD scenarios."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import random

from fastapi import APIRouter, BackgroundTasks, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from ...models.gitlab import GitLabWebhook, GitLabJobStatus
from ...models.orchestrator import OrchestrationRequest  
from ...models.email import ProcessedEmail
from ...services.orchestration_service import OrchestrationService
from ...services.gitlab_client import GitLabClient
from ...core.database import get_database_session
from ...utils.mock_data import mock_loader

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/test", tags=["🧪 Testing & Simulation"])


# Helper functions
def _normalize_webhook_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize webhook payload to match GitLab models.
    
    Handles common webhook validation issues:
    - Ensures nested project has namespace and path_with_namespace
    - Fixes commit.author format to match GitLabUser model
    - Normalizes build status values to match GitLabJobStatus
    """
    data = dict(data)  # Work on copy to avoid mutations
    
    # Fix project fields
    project = dict(data.get("project") or {})
    if "namespace" not in project:
        pwn = project.get("path_with_namespace") or ""
        project["namespace"] = pwn.split("/", 1)[0] if "/" in pwn else "test"
    if "path_with_namespace" not in project and project.get("name"):
        project["path_with_namespace"] = f"{project['namespace']}/{project['name']}"
    data["project"] = project
    
    # Handle incomplete commit.author
    commit = data.get("commit")
    if commit:
        author = commit.get("author") or {}
        required = {"id", "username", "name"} 
        if not isinstance(author, dict) or not required.issubset(author.keys()):
            data.pop("commit", None)
        elif "url" not in commit and project.get("web_url") and commit.get("id"):
            commit["url"] = f"{project['web_url']}/-/commit/{commit['id']}"
            
    # Fix builds project and status fields
    if isinstance(data.get("builds"), list):
        fixed_builds = []
        valid_statuses = {s.value for s in GitLabJobStatus}
        for build in data["builds"]:
            build = dict(build)
            # Ensure build project has required fields
            build_project = dict(build.get("project") or {})
            if not build_project:
                build["project"] = project
            else:
                if "namespace" not in build_project:
                    pwn = build_project.get("path_with_namespace") or project["path_with_namespace"]
                    build_project["namespace"] = pwn.split("/", 1)[0]
                if "path_with_namespace" not in build_project and build_project.get("name"):
                    build_project["path_with_namespace"] = f"{build_project['namespace']}/{build_project['name']}"
                build["project"] = build_project
                
            # Normalize status if needed
            if (status := build.get("status")) and status not in valid_statuses:
                # GitLabJobStatus enum will handle validation
                pass
            fixed_builds.append(build)
        data["builds"] = fixed_builds
            
    return data


def get_orchestration_service() -> OrchestrationService:
    """Get orchestration service instance."""
    return OrchestrationService()


# Request/Response Models
class CustomWebhookRequest(BaseModel):
    """Request model for custom webhook generation."""
    project_id: int = Field(default=2001, ge=1, description="Project ID")
    pipeline_status: str = Field(
        default="failed", 
        pattern="^(failed|success|running|pending|canceled)$",
        description="Pipeline status"
    )
    job_name: str = Field(default="test", min_length=1, max_length=100)
    branch: str = Field(default="main", min_length=1, max_length=100) 
    commit_message: str = Field(default="Test commit", min_length=1, max_length=500)
    include_logs: bool = Field(default=True, description="Include sample error logs")


class TestScenarioResponse(BaseModel):
    """Response model for test scenarios."""
    scenario: str
    description: str  
    webhook_payload: Dict[str, Any]
    request_id: str
    status: str = "processing"
    message: str


class TestEnvironmentStatus(BaseModel):
    """Test environment status response."""
    test_environment: str = "active"
    mock_data_available: bool = True
    available_scenarios: List[str]
    quick_start: Dict[str, str]
    api_documentation: str = "/docs"
    sample_endpoints: Dict[str, str]


# Routes 
@router.get("/", response_model=TestEnvironmentStatus)
async def test_environment_info() -> TestEnvironmentStatus:
    """🏠 Get test environment information and available scenarios."""

    try:
        # Get available scenarios
        scenarios = mock_loader.list_available_scenarios()
        all_scenarios = []
        for scenario_type, scenario_names in scenarios.items():
            all_scenarios.extend([f"{scenario_type}/{name}" for name in scenario_names])

        return TestEnvironmentStatus(
            available_scenarios=all_scenarios,
            quick_start={
                "1": "Visit /docs for full API documentation",
                "2": "Try GET /test/scenarios/failed_build for a quick test",
                "3": "Use POST /test/webhook/custom for custom scenarios", 
                "4": "Check /health/detailed for system status"
            },
            sample_endpoints={
                "health_check": "/health/",
                "detailed_health": "/health/detailed",
                "webhook_info": "/webhooks/gitlab/info",
                "test_scenarios": "/test/scenarios/",
                "custom_webhook": "/test/webhook/custom"
            }
        )

    except Exception as e:
        logger.error("Failed to get test environment info", error=str(e))
        return TestEnvironmentStatus(
            available_scenarios=[],
            quick_start={
                "error": "Failed to load test environment",
                "1": "Check server logs for details"
            },
            sample_endpoints={}
        )


@router.get("/scenarios/", response_model=Dict[str, List[str]])
async def list_test_scenarios() -> Dict[str, List[str]]:
    """📋 List all available test scenarios organized by type."""
        
    try:
        return mock_loader.list_available_scenarios()
    except Exception as e:
        logger.error("Failed to list scenarios", error=str(e))
        return {"error": [f"Failed to load scenarios: {str(e)}"]}


@router.get("/scenarios/{scenario_name}", response_model=TestScenarioResponse)
async def trigger_test_scenario(
    scenario_name: str,
    background_tasks: BackgroundTasks,
    orchestration_service: OrchestrationService = Depends(get_orchestration_service)
) -> TestScenarioResponse:
    """🎯 Trigger a predefined test scenario."""
        
    # Map scenario names to types
    scenario_mapping = {
        "failed_build": ("pipeline", "failed_build"),
        "test_failure": ("test", "test_failure"),
        "integration_failure": ("test", "integration_failure"),
        "docker_build_failure": ("deployment", "docker_build_failure"),
        "security_scan_failure": ("deployment", "security_scan_failure")
    }

    if scenario_name not in scenario_mapping:
        raise HTTPException(
            status_code=404,
            detail=f"Scenario '{scenario_name}' not found. Available: {list(scenario_mapping.keys())}"
        )

    try:
        scenario_type, scenario_key = scenario_mapping[scenario_name]
        scenario_data = mock_loader.get_scenario(scenario_type, scenario_key)
        
        if not scenario_data or "webhook" not in scenario_data:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to load scenario data for '{scenario_name}'"
            )

        # Process webhook in background
        webhook_payload = scenario_data["webhook"]
        webhook_data = _normalize_webhook_data(webhook_payload)
        try:
            webhook_model = GitLabWebhook.model_validate(webhook_data)  # type: ignore
        except AttributeError:
            webhook_model = GitLabWebhook.parse_obj(webhook_data)  # type: ignore

        # Generate request ID
        request_id = f"test_{scenario_name}_{random.randint(1000000000, 9999999999)}"
        
        # Create orchestration request
        request = OrchestrationRequest(
            webhook_data=webhook_model,
            priority=7 if webhook_model.object_attributes.status == "failed" else 5,
            include_context=True,
            include_repository_files=False
        )

        # Process in background
        background_tasks.add_task(orchestration_service.process_webhook, request, request_id)
        
        logger.info(
            "Test scenario triggered",
            scenario=scenario_name,
            request_id=request_id,
            project_id=webhook_model.project.id
        )
        
    except Exception as e:
        logger.error("Failed to process test scenario", scenario=scenario_name, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to process scenario: {str(e)}")
        
    return TestScenarioResponse(
        scenario=scenario_name,
        description=scenario_data.get("description", scenario_name),
        webhook_payload=webhook_data,
        request_id=request_id,
        message=f"Test scenario '{scenario_name}' triggered successfully. Check /analysis/{request_id} for results."
    )


@router.post("/webhook/custom", response_model=TestScenarioResponse)
async def create_custom_webhook(
    request: CustomWebhookRequest,
    background_tasks: BackgroundTasks,
    orchestration_service: OrchestrationService = Depends(get_orchestration_service)
) -> TestScenarioResponse:
    """🔧 Create and trigger a custom webhook scenario."""
        
    try:
        # Generate webhook using mock loader
        webhook_payload = mock_loader.create_custom_webhook(
            project_id=request.project_id,
            pipeline_status=request.pipeline_status,
            job_name=request.job_name,
            branch=request.branch,
            commit_message=request.commit_message,
            include_logs=request.include_logs
        )

        # Normalize and convert to model
        webhook_data = _normalize_webhook_data(webhook_payload)
        try:
            webhook_model = GitLabWebhook.model_validate(webhook_data)  # type: ignore
        except AttributeError:
            webhook_model = GitLabWebhook.parse_obj(webhook_data)  # type: ignore
        
        # Create and trigger request
        request_id = f"custom_{request.project_id}_{random.randint(1000000000, 9999999999)}"
        orchestration_request = OrchestrationRequest(
            webhook_data=webhook_model,
            priority=7 if request.pipeline_status == "failed" else 5,
            include_context=True,
            include_repository_files=False
        )

        # Prepare response first
        response = TestScenarioResponse(
            scenario="custom",
            description=f"Custom webhook for project {request.project_id} with {request.pipeline_status} status",
            webhook_payload=webhook_data,
            request_id=request_id,
            message=f"Custom webhook triggered successfully. Check /analysis/{request_id} for results."
        )

        # Log before starting background task
        logger.info(
            "Custom webhook triggered",
            project_id=request.project_id,
            status=request.pipeline_status,
            request_id=request_id
        )
        
        # Add background task with async wrapper
        async def run_async_webhook():
            await orchestration_service.process_webhook(orchestration_request, request_id)
        
        background_tasks.add_task(run_async_webhook)
        return response
        
    except Exception as e:
        logger.error("Failed to process custom webhook", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to process webhook: {str(e)}")


@router.get("/mock/projects", response_model=List[Dict[str, Any]])
async def get_mock_projects() -> List[Dict[str, Any]]:
    """📂 Get list of mock projects."""
    try:
        return mock_loader.get_base_data("projects")
    except Exception as e:
        logger.error("Failed to get mock projects", error=str(e))
        return []


@router.get("/mock/users", response_model=List[Dict[str, Any]])
async def get_mock_users() -> List[Dict[str, Any]]:
    """👥 Get list of mock users."""
    try: 
        return mock_loader.get_base_data("users")
    except Exception as e:
        logger.error("Failed to get mock users", error=str(e))
        return []


@router.post("/mock/reload")
async def reload_mock_data() -> Dict[str, str]:
    """🔄 Reload mock data cache."""
    try:
        mock_loader.clear_cache()
        scenarios = mock_loader.list_available_scenarios()
        total_scenarios = sum(len(names) for names in scenarios.values())
        
        return {
            "status": "success",
            "message": f"Mock data reloaded. Found {total_scenarios} scenarios across {len(scenarios)} types."
        }
    except Exception as e:
        logger.error("Failed to reload mock data", error=str(e))
        return {
            "status": "error",
            "message": f"Failed to reload mock data: {str(e)}"
        }


# ===== GitLab Email Processing Test Endpoints =====

@router.post("/simulate-gitlab-email")
async def simulate_gitlab_email_processing(
    project_id: str = "2522",
    pipeline_id: str = "166693", 
    project_name: str = "jobOFFByAccount",
    project_path: str = "svs/jobs/joboffbyaccount",
    pipeline_ref: str = "uat-19092025",
    pipeline_status: str = "failed",
    db: AsyncSession = Depends(get_database_session)
):
    """🧪 Simulate processing a GitLab pipeline email with real data."""
    try:
        from datetime import timezone
        
        logger.info(
            "Starting GitLab email simulation",
            project_id=project_id,
            pipeline_id=pipeline_id,
            project_name=project_name
        )
        
        # Create test processed email record
        test_email = ProcessedEmail(
            message_uid=f"test-{datetime.now().timestamp()}",
            message_id=f"<test-{project_id}-{pipeline_id}@gitlab.example.com>",
            received_at=datetime.now(timezone.utc).replace(tzinfo=None),
            from_email="gitlab@example.com",
            subject=f"Pipeline #{pipeline_id} has {pipeline_status} for {project_name}",
            project_id=project_id,
            project_name=project_name,
            project_path=project_path,
            pipeline_id=pipeline_id,
            pipeline_ref=pipeline_ref,
            pipeline_status=pipeline_status,
            status="pending",
            error_message=f"Test email simulation for pipeline {pipeline_id}"
        )
        
        db.add(test_email)
        await db.commit()
        
        # Update status to fetching GitLab data
        test_email.status = "fetching_gitlab_data"
        await db.commit()
        
        # Fetch real GitLab logs using existing client
        try:
            gitlab_client = GitLabClient()
            async with gitlab_client as client:
                failed_jobs = await client.get_failed_jobs(project_id, pipeline_id)
                
                if failed_jobs:
                    all_logs = []
                    for job in failed_jobs:
                        try:
                            job_log = await client.get_job_log(
                                project_id,
                                job.id,
                                max_size_mb=5,
                                context_lines=50
                            )
                            
                            log_entry = f"""
=== JOB: {job_log.job_name} (ID: {job_log.job_id}) ===
Stage: {job_log.stage}
Status: {job_log.status}
Failure Reason: {job_log.failure_reason or 'N/A'}
Duration: {job_log.duration or 0}s

{job_log.log_content}

=== END JOB ===

"""
                            all_logs.append(log_entry)
                        except Exception as job_error:
                            logger.warning("Failed to get job log", job_id=job.id, error=str(job_error))
                    
                    if all_logs:
                        combined_logs = "\n".join(all_logs)
                        test_email.gitlab_error_log = combined_logs
                        test_email.status = "completed"
                    else:
                        test_email.status = "no_gitlab_logs"
                else:
                    test_email.status = "no_failed_jobs"
                    
        except Exception as e:
            test_email.status = "error"
            test_email.error_message = f"GitLab API error: {str(e)}"
            logger.error("Failed to fetch GitLab logs", error=str(e))
        
        await db.commit()
        
        return {
            "status": "success",
            "message": "GitLab email simulation completed",
            "data": {
                "email_id": test_email.id,
                "project_id": project_id,
                "pipeline_id": pipeline_id,
                "project_name": project_name,
                "final_status": test_email.status,
                "has_gitlab_logs": bool(test_email.gitlab_error_log),
                "gitlab_log_size": len(test_email.gitlab_error_log) if test_email.gitlab_error_log else 0
            }
        }
        
    except Exception as e:
        logger.error("Error in GitLab email simulation", error=str(e))
        raise HTTPException(status_code=500, detail=f"Simulation failed: {str(e)}")


@router.get("/gitlab-logs/{project_id}/{pipeline_id}")
async def get_gitlab_logs_direct(project_id: str, pipeline_id: str):
    """🔍 Directly fetch GitLab logs for testing API connectivity."""
    try:
        gitlab_client = GitLabClient()
        async with gitlab_client as client:
            # Get pipeline details
            pipeline = await client.get_pipeline(project_id, pipeline_id)
            
            # Get failed jobs and logs
            failed_jobs = await client.get_failed_jobs(project_id, pipeline_id)
            
            job_logs = []
            for job in failed_jobs[:3]:  # Limit to first 3 jobs
                try:
                    job_log = await client.get_job_log(project_id, job.id, max_size_mb=2, context_lines=30)
                    job_logs.append({
                        "job_id": job_log.job_id,
                        "job_name": job_log.job_name,
                        "stage": job_log.stage,
                        "status": job_log.status,
                        "failure_reason": job_log.failure_reason,
                        "log_preview": job_log.log_content[:500] + "..." if len(job_log.log_content) > 500 else job_log.log_content
                    })
                except Exception as e:
                    job_logs.append({"job_id": job.id, "error": str(e)})
            
            return {
                "status": "success",
                "data": {
                    "project_id": project_id,
                    "pipeline_id": pipeline_id,
                    "pipeline_status": pipeline.status,
                    "pipeline_ref": pipeline.ref,
                    "failed_jobs_count": len(failed_jobs),
                    "job_logs": job_logs
                }
            }
            
    except Exception as e:
        logger.error("Error fetching GitLab logs", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch logs: {str(e)}")


@router.get("/processed-emails")
async def get_processed_emails(
    limit: int = 10,
    db: AsyncSession = Depends(get_database_session)
):
    """📧 Get recent processed emails for testing."""
    try:
        from sqlalchemy import select, desc
        
        result = await db.execute(
            select(ProcessedEmail)
            .order_by(desc(ProcessedEmail.processed_at))
            .limit(limit)
        )
        emails = result.scalars().all()
        
        email_data = []
        for email in emails:
            email_data.append({
                "id": email.id,
                "subject": email.subject,
                "project_name": email.project_name,
                "pipeline_id": email.pipeline_id,
                "pipeline_status": email.pipeline_status,
                "status": email.status,
                "processed_at": email.processed_at,
                "has_gitlab_logs": bool(email.gitlab_error_log),
                "gitlab_log_size": len(email.gitlab_error_log) if email.gitlab_error_log else 0
            })
        
        return {
            "status": "success",
            "count": len(email_data),
            "emails": email_data
        }
        
    except Exception as e:
        logger.error("Error fetching processed emails", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch emails: {str(e)}")