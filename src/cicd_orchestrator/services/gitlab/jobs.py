"""Job-related GitLab API operations."""

from typing import Any, Dict, List, Optional, Union

import httpx
import structlog

from ...core.exceptions import GitLabAPIError
from ...models.gitlab import GitLabJob, GitLabJobLog
from .base_client import BaseClient
from .log_processor import LogProcessor

logger = structlog.get_logger(__name__)


class JobOperations(BaseClient):
    """Job-related GitLab API operations."""

    async def get_job(self, project_id: Union[int, str], job_id: int) -> GitLabJob:
        """Get job information.
        
        Args:
            project_id: Project ID or path with namespace
            job_id: Job ID
            
        Returns:
            GitLab job information
        """
        endpoint = f"/projects/{project_id}/jobs/{job_id}"
        data = await self._make_request("GET", endpoint)
        
        return GitLabJob(**data)

    async def get_job_log(
        self, 
        project_id: Union[int, str], 
        job_id: int,
        max_size_mb: Optional[int] = None,
        context_lines: Optional[int] = None
    ) -> GitLabJobLog:
        """Get job log content with optional size and context limitations.
        
        Args:
            project_id: Project ID or path with namespace
            job_id: Job ID
            max_size_mb: Maximum log size in MB (None for no limit)
            context_lines: Number of context lines around errors (None for full log)
            
        Returns:
            Job log information
        """
        # Get job info first
        job = await self.get_job(project_id, job_id)
        
        # Get log content
        endpoint = f"/projects/{project_id}/jobs/{job_id}/trace"
        session = await self._ensure_session()
        
        try:
            response = await session.get(endpoint)
            response.raise_for_status()
            log_content = response.text
            
            # Apply size and context filtering
            log_content = LogProcessor.process_log_content(
                log_content, 
                max_size_mb=max_size_mb,
                context_lines=context_lines,
                job_status=job.status
            )
            
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                log_content = "Log not available or job has not started yet."
            else:
                raise GitLabAPIError(f"Failed to get job log: {e}")
        
        return GitLabJobLog(
            job_id=job.id,
            job_name=job.name,
            stage=job.stage,
            status=job.status,
            log_content=log_content,
            failure_reason=job.failure_reason,
            started_at=job.started_at,
            finished_at=job.finished_at,
            duration=job.duration,
            runner_description=job.runner.get("description") if job.runner else None,
        )

    async def get_job_artifacts_info(
        self, 
        project_id: Union[int, str], 
        job_ids: List[int]
    ) -> List[Dict[str, Any]]:
        """Get artifacts information for multiple jobs.
        
        Args:
            project_id: Project ID or path with namespace
            job_ids: List of job IDs
            
        Returns:
            List of artifacts information
        """
        artifacts_info = []
        
        for job_id in job_ids:
            try:
                endpoint = f"/projects/{project_id}/jobs/{job_id}/artifacts"
                response_data = await self._make_request("GET", endpoint)
                
                # Get artifacts metadata
                artifacts_info.append({
                    "job_id": job_id,
                    "artifacts_available": True,
                    "artifacts_info": response_data
                })
            except GitLabAPIError as e:
                if e.status_code == 404:
                    artifacts_info.append({
                        "job_id": job_id,
                        "artifacts_available": False,
                        "error": "No artifacts found"
                    })
                else:
                    logger.warning(
                        "Failed to fetch artifacts info",
                        job_id=job_id,
                        error=str(e)
                    )
        
        return artifacts_info