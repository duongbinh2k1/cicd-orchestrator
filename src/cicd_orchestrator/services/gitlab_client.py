"""GitLab API client for fetching project, pipeline, and job information."""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import httpx
import structlog

from ..core.config import settings
from ..models.gitlab import (
    GitLabJob,
    GitLabJobLog,
    GitLabJobStatus,
    GitLabPipeline,
    GitLabProject,
    GitLabProjectInfo,
    GitLabUser,
)

logger = structlog.get_logger(__name__)


class GitLabAPIError(Exception):
    """Custom exception for GitLab API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None, response_data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


class GitLabClient:
    """Async GitLab API client."""

    def __init__(
        self,
        base_url: str = "https://gitlab.com",
        api_token: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        """Initialize GitLab client.
        
        Args:
            base_url: GitLab instance base URL
            api_token: GitLab API token
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
        """
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}/api/v4"
        self.api_token = api_token or settings.gitlab_api_token
        self.timeout = timeout
        self.max_retries = max_retries
        
        self._session: Optional[httpx.AsyncClient] = None
        
        if not self.api_token:
            raise ValueError("GitLab API token is required")

    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def _ensure_session(self) -> httpx.AsyncClient:
        """Ensure HTTP session is available."""
        if self._session is None or self._session.is_closed:
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
                "User-Agent": "cicd-orchestrator/1.0",
            }
            
            self._session = httpx.AsyncClient(
                base_url=self.api_url,
                headers=headers,
                timeout=httpx.Timeout(self.timeout),
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            )
        
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.is_closed:
            await self._session.aclose()

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        retry_count: int = 0,
    ) -> Dict[str, Any]:
        """Make HTTP request with retry logic.
        
        Args:
            method: HTTP method
            endpoint: API endpoint
            params: Query parameters
            json_data: JSON request body
            retry_count: Current retry attempt
            
        Returns:
            JSON response data
            
        Raises:
            GitLabAPIError: When API request fails
        """
        session = await self._ensure_session()
        
        try:
            logger.debug(
                "Making GitLab API request",
                method=method,
                endpoint=endpoint,
                params=params,
                retry_count=retry_count,
            )
            
            response = await session.request(
                method=method,
                url=endpoint,
                params=params,
                json=json_data,
            )
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                raise GitLabAPIError(
                    f"Resource not found: {endpoint}",
                    status_code=response.status_code,
                    response_data=response.json() if response.content else None,
                )
            elif response.status_code == 403:
                raise GitLabAPIError(
                    "Access denied. Check API token permissions.",
                    status_code=response.status_code,
                    response_data=response.json() if response.content else None,
                )
            elif response.status_code == 429:
                # Rate limit exceeded
                if retry_count < self.max_retries:
                    wait_time = 2 ** retry_count
                    logger.warning(
                        "Rate limit exceeded, retrying",
                        wait_time=wait_time,
                        retry_count=retry_count,
                    )
                    await asyncio.sleep(wait_time)
                    return await self._make_request(method, endpoint, params, json_data, retry_count + 1)
                else:
                    raise GitLabAPIError(
                        "Rate limit exceeded. Max retries reached.",
                        status_code=response.status_code,
                    )
            else:
                response.raise_for_status()
                
        except httpx.RequestError as e:
            if retry_count < self.max_retries:
                wait_time = 2 ** retry_count
                logger.warning(
                    "Request failed, retrying",
                    error=str(e),
                    wait_time=wait_time,
                    retry_count=retry_count,
                )
                await asyncio.sleep(wait_time)
                return await self._make_request(method, endpoint, params, json_data, retry_count + 1)
            else:
                raise GitLabAPIError(f"Request failed after {self.max_retries} retries: {e}")
        
        except Exception as e:
            logger.error("Unexpected error during GitLab API request", error=str(e))
            raise GitLabAPIError(f"Unexpected error: {e}")

    async def get_project(self, project_id: Union[int, str]) -> GitLabProject:
        """Get project information.
        
        Args:
            project_id: Project ID or path with namespace
            
        Returns:
            GitLab project information
        """
        endpoint = f"/projects/{project_id}"
        data = await self._make_request("GET", endpoint)
        
        return GitLabProject(**data)

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
            log_content = self._process_log_content(
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
    
    def _process_log_content(
        self, 
        log_content: str, 
        max_size_mb: Optional[int] = None,
        context_lines: Optional[int] = None,
        job_status: str = "failed"
    ) -> str:
        """Process log content based on size and context constraints."""
        
        # Apply size limit first
        if max_size_mb:
            max_bytes = max_size_mb * 1024 * 1024
            if len(log_content.encode('utf-8')) > max_bytes:
                # Take the last portion of the log (where errors usually are)
                log_content = log_content[-max_bytes//2:]  # Take last half
                log_content = "... [LOG TRUNCATED DUE TO SIZE] ...\n" + log_content
        
        # Apply context filtering for failed jobs
        if context_lines and job_status in ["failed", "canceled"] and log_content:
            log_content = self._extract_error_context(log_content, context_lines)
        
        return log_content
    
    def _extract_error_context(self, log_content: str, context_lines: int) -> str:
        """Extract relevant error context from log content."""
        lines = log_content.split('\n')
        
        # Common error indicators
        error_patterns = [
            'error:', 'Error:', 'ERROR:', 'FAILED:', 'failed:',
            'exception:', 'Exception:', 'EXCEPTION:',
            'fatal:', 'Fatal:', 'FATAL:',
            'build failed', 'Build failed', 'BUILD FAILED',
            'test failed', 'Test failed', 'TEST FAILED',
            'compilation failed', 'Compilation failed',
            'exit code', 'Exit code', 'exit status'
        ]
        
        error_line_indices = []
        for i, line in enumerate(lines):
            if any(pattern in line for pattern in error_patterns):
                error_line_indices.append(i)
        
        if not error_line_indices:
            # If no specific errors found, return the last portion
            return '\n'.join(lines[-context_lines*2:])
        
        # Extract context around error lines
        context_lines_set = set()
        for error_idx in error_line_indices:
            start = max(0, error_idx - context_lines)
            end = min(len(lines), error_idx + context_lines + 1)
            context_lines_set.update(range(start, end))
        
        # Sort and extract context
        sorted_indices = sorted(context_lines_set)
        context_content = []
        
        prev_idx = -1
        for idx in sorted_indices:
            if idx > prev_idx + 1:
                context_content.append("... [CONTEXT GAP] ...")
            context_content.append(f"{idx+1:4d}: {lines[idx]}")
            prev_idx = idx
        
        return '\n'.join(context_content)

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

    async def get_project_info(self, project_id: Union[int, str], include_pipeline: bool = True) -> GitLabProjectInfo:
        """Get comprehensive project information.
        
        Args:
            project_id: Project ID or path with namespace
            include_pipeline: Whether to include latest pipeline info
            
        Returns:
            Comprehensive project information
        """
        project = await self.get_project(project_id)
        
        latest_pipeline = None
        failed_jobs = []
        
        if include_pipeline:
            try:
                # Get latest pipeline
                endpoint = f"/projects/{project_id}/pipelines"
                params = {"order_by": "id", "sort": "desc", "per_page": 1}
                pipelines_data = await self._make_request("GET", endpoint, params=params)
                
                if pipelines_data:
                    latest_pipeline = GitLabPipeline(**pipelines_data[0])
                    
                    # Get failed jobs from latest pipeline if it failed
                    if latest_pipeline.status in ["failed", "canceled"]:
                        failed_jobs = await self.get_failed_jobs(project_id, latest_pipeline.id)
                        
            except GitLabAPIError as e:
                logger.warning("Failed to get pipeline info", error=str(e))
        
        return GitLabProjectInfo(
            project=project,
            latest_pipeline=latest_pipeline,
            failed_jobs=failed_jobs,
        )

    async def get_project_files(
        self,
        project_id: Union[int, str],
        path: str = "",
        ref: str = "main",
        recursive: bool = False,
    ) -> List[str]:
        """Get list of files in project repository.
        
        Args:
            project_id: Project ID or path with namespace
            path: Repository path to list
            ref: Git reference (branch, tag, commit)
            recursive: Whether to list files recursively
            
        Returns:
            List of file paths
        """
        endpoint = f"/projects/{project_id}/repository/tree"
        params = {
            "path": path,
            "ref": ref,
            "recursive": recursive,
            "per_page": 100,
        }
        
        files = []
        page = 1
        
        while True:
            params["page"] = page
            data = await self._make_request("GET", endpoint, params=params)
            
            if not data:
                break
                
            for item in data:
                if item["type"] == "blob":  # Files only, not directories
                    files.append(item["path"])
            
            # Check if there are more pages
            if len(data) < 100:
                break
                
            page += 1
        
        return files

    async def get_ci_config(self, project_id: Union[int, str], ref: str = "main") -> Optional[Dict[str, Any]]:
        """Get CI/CD configuration file content.
        
        Args:
            project_id: Project ID or path with namespace
            ref: Git reference (branch, tag, commit)
            
        Returns:
            CI/CD configuration as dictionary or None if not found
        """
        # Try common CI config file names
        config_files = [".gitlab-ci.yml", ".gitlab-ci.yaml", "ci.yml", "ci.yaml"]
        
        for config_file in config_files:
            try:
                endpoint = f"/projects/{project_id}/repository/files/{config_file.replace('/', '%2F')}"
                params = {"ref": ref}
                data = await self._make_request("GET", endpoint, params=params)
                
                if data and "content" in data:
                    import base64
                    import yaml
                    
                    # Decode base64 content
                    content = base64.b64decode(data["content"]).decode("utf-8")
                    
                    # Parse YAML
                    try:
                        return yaml.safe_load(content)
                    except yaml.YAMLError as e:
                        logger.warning(f"Failed to parse CI config {config_file}", error=str(e))
                        continue
                        
            except GitLabAPIError:
                continue
        
        return None

    async def search_projects(
        self,
        search: str,
        membership: bool = True,
        owned: bool = False,
        starred: bool = False,
    ) -> List[GitLabProject]:
        """Search for projects.
        
        Args:
            search: Search query
            membership: Limit to projects user is a member of
            owned: Limit to projects owned by user
            starred: Limit to starred projects
            
        Returns:
            List of matching projects
        """
        endpoint = "/projects"
        params = {
            "search": search,
            "membership": membership,
            "owned": owned,
            "starred": starred,
            "per_page": 50,
        }
        
        data = await self._make_request("GET", endpoint, params=params)
        return [GitLabProject(**project_data) for project_data in data]

    async def health_check(self) -> bool:
        """Check if GitLab API is accessible.
        
        Returns:
            True if API is accessible, False otherwise
        """
        try:
            endpoint = "/user"
            await self._make_request("GET", endpoint)
            return True
        except GitLabAPIError:
            return False
