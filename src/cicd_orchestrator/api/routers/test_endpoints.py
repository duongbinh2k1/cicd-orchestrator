"""🧪 Test endpoints for simulating GitLab webhooks and CI/CD scenarios."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import random

from fastapi import APIRouter, BackgroundTasks, Depends, Query, HTTPException
from pydantic import BaseModel, Field
import structlog

from ...models.gitlab import GitLabWebhook, GitLabJobStatus
from ...models.orchestrator import OrchestrationRequest
from ...services.orchestration_service import OrchestrationService
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