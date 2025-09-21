"""Unified GitLab API client combining all operations."""

from typing import Any, Dict, List, Optional, Union

from ...core.exceptions import GitLabAPIError
from .base_client import BaseClient
from .jobs import JobOperations
from .pipelines import PipelineOperations
from .projects import ProjectOperations
from ...models.gitlab import (
    GitLabJob,
    GitLabJobLog,
    GitLabPipeline,
    GitLabProject,
    GitLabProjectInfo,
)


class GitLabClient(BaseClient):
    """Unified GitLab API client with all operations."""

    def __init__(self, base_url: str, api_token: str, timeout: int = 30):
        """Initialize GitLab client.
        
        Args:
            base_url: GitLab instance URL
            api_token: GitLab API token
            timeout: Request timeout in seconds
        """
        super().__init__(base_url, api_token, timeout)
        
        # Initialize operation handlers with shared session
        self._projects = ProjectOperations(base_url, api_token, timeout)
        self._pipelines = PipelineOperations(base_url, api_token, timeout)
        self._jobs = JobOperations(base_url, api_token, timeout)

    # Delegate project operations
    async def get_project(self, project_id: Union[int, str]):
        """Get project information."""
        return await self._projects.get_project(project_id)
    
    async def get_project_info(self, project_id: Union[int, str], include_pipeline: bool = True):
        """Get detailed project information."""
        return await self._projects.get_project_info(project_id, include_pipeline)
    
    async def get_project_files(self, project_id: Union[int, str], path: str = "", ref: str = "main"):
        """Get project files."""
        return await self._projects.get_project_files(project_id, path, ref)
    
    async def search_projects(self, search: str, per_page: int = 20):
        """Search projects."""
        return await self._projects.search_projects(search, per_page)
    
    async def get_ci_config(self, project_id: Union[int, str], ref: str = "main"):
        """Get CI configuration."""
        return await self._projects.get_ci_config(project_id, ref)

    # Delegate pipeline operations
    async def get_pipeline(self, project_id: Union[int, str], pipeline_id: int):
        """Get pipeline information."""
        return await self._pipelines.get_pipeline(project_id, pipeline_id)
    
    async def get_pipeline_jobs(self, project_id: Union[int, str], pipeline_id: int):
        """Get pipeline jobs."""
        return await self._pipelines.get_pipeline_jobs(project_id, pipeline_id)
    
    async def get_failed_jobs(self, project_id: Union[int, str], pipeline_id: int):
        """Get failed jobs from pipeline."""
        return await self._pipelines.get_failed_jobs(project_id, pipeline_id)
    
    async def get_pipeline_test_report(self, project_id: Union[int, str], pipeline_id: int):
        """Get pipeline test report."""
        return await self._pipelines.get_pipeline_test_report(project_id, pipeline_id)

    # Delegate job operations
    async def get_job(self, project_id: Union[int, str], job_id: int):
        """Get job information."""
        return await self._jobs.get_job(project_id, job_id)
    
    async def get_job_log(self, project_id: Union[int, str], job_id: int, max_size_mb: Optional[int] = None, context_lines: Optional[int] = None):
        """Get job log."""
        return await self._jobs.get_job_log(project_id, job_id, max_size_mb, context_lines)
    
    async def get_job_artifacts_info(self, project_id: Union[int, str], job_ids: List[int]):
        """Get job artifacts info."""
        return await self._jobs.get_job_artifacts_info(project_id, job_ids)

    async def close(self):
        """Close all HTTP sessions."""
        await super().close()
        await self._projects.close()
        await self._pipelines.close()
        await self._jobs.close()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def health_check(self) -> bool:
        """Check GitLab API health."""
        try:
            # Simple API call to check connectivity
            await self._make_request("GET", "/user")
            return True
        except Exception:
            return False