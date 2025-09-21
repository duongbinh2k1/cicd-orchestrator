"""Project-related GitLab API operations."""

from typing import List, Union

import structlog

from ...core.exceptions import GitLabAPIError
from ...models.gitlab import GitLabProject, GitLabProjectInfo, GitLabPipeline
from .base_client import BaseClient

logger = structlog.get_logger(__name__)


class ProjectOperations(BaseClient):
    """Project-related GitLab API operations."""

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
                        # Import here to avoid circular imports
                        from .pipelines import PipelineOperations
                        pipeline_ops = PipelineOperations(
                            base_url=self.base_url,
                            api_token=self.api_token,
                            timeout=self.timeout,
                            max_retries=self.max_retries
                        )
                        failed_jobs = await pipeline_ops.get_failed_jobs(project_id, latest_pipeline.id)
                        
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
        
        try:
            data = await self._make_request("GET", endpoint, params=params)
            return [item["path"] for item in data if item["type"] == "blob"]
        except GitLabAPIError as e:
            logger.warning("Failed to get project files", error=str(e))
            return []

    async def get_ci_config(self, project_id: Union[int, str], ref: str = "main") -> dict:
        """Get CI configuration for project.
        
        Args:
            project_id: Project ID or path with namespace
            ref: Git reference (branch, tag, commit)
            
        Returns:
            CI configuration dict, None if not found
        """
        endpoint = f"/projects/{project_id}/ci/lint"
        params = {"ref": ref}
        
        try:
            # First try to get the .gitlab-ci.yml content
            file_endpoint = f"/projects/{project_id}/repository/files/.gitlab-ci.yml"
            file_params = {"ref": ref}
            
            file_data = await self._make_request("GET", file_endpoint, params=file_params)
            
            if file_data and "content" in file_data:
                import base64
                import yaml
                
                # Decode base64 content
                content = base64.b64decode(file_data["content"]).decode("utf-8")
                
                # Parse YAML
                ci_config = yaml.safe_load(content)
                return ci_config
                
        except GitLabAPIError:
            logger.debug("No CI configuration found", project_id=project_id, ref=ref)
        except Exception as e:
            logger.warning("Failed to parse CI config", error=str(e))
        
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