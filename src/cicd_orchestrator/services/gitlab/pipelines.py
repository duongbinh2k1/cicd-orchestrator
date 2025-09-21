"""Pipeline-related GitLab API operations."""

from typing import Any, Dict, List, Optional, Union

import structlog

from ...core.exceptions import GitLabAPIError
from ...models.gitlab import GitLabJob, GitLabJobStatus, GitLabPipeline
from .base_client import BaseClient

logger = structlog.get_logger(__name__)


class PipelineOperations(BaseClient):
    """Pipeline-related GitLab API operations."""

    async def get_pipeline(self, project_id: Union[int, str], pipeline_id: int) -> GitLabPipeline:
        """Get pipeline information.
        
        Args:
            project_id: Project ID or path with namespace
            pipeline_id: Pipeline ID
            
        Returns:
            GitLab pipeline information
        """
        endpoint = f"/projects/{project_id}/pipelines/{pipeline_id}"
        data = await self._make_request("GET", endpoint)
        
        return GitLabPipeline(**data)

    async def get_pipeline_jobs(self, project_id: Union[int, str], pipeline_id: int) -> List[GitLabJob]:
        """Get jobs for a specific pipeline.
        
        Args:
            project_id: Project ID or path with namespace
            pipeline_id: Pipeline ID
            
        Returns:
            List of pipeline jobs
        """
        endpoint = f"/projects/{project_id}/pipelines/{pipeline_id}/jobs"
        data = await self._make_request("GET", endpoint)
        
        return [GitLabJob(**job_data) for job_data in data]

    async def get_failed_jobs(self, project_id: Union[int, str], pipeline_id: int) -> List[GitLabJob]:
        """Get failed jobs for a specific pipeline.
        
        Args:
            project_id: Project ID or path with namespace
            pipeline_id: Pipeline ID
            
        Returns:
            List of failed jobs
        """
        jobs = await self.get_pipeline_jobs(project_id, pipeline_id)
        return [job for job in jobs if job.status == GitLabJobStatus.FAILED]

    async def get_pipeline_test_report(
        self, 
        project_id: Union[int, str], 
        pipeline_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get pipeline test report.
        
        Args:
            project_id: Project ID or path with namespace
            pipeline_id: Pipeline ID
            
        Returns:
            Test report data or None if not available
        """
        endpoint = f"/projects/{project_id}/pipelines/{pipeline_id}/test_report"
        
        try:
            response_data = await self._make_request("GET", endpoint)
            return response_data
        except GitLabAPIError as e:
            if e.status_code == 404:
                return None
            raise