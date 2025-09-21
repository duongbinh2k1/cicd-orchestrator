"""
GitLab API client modules.

This package provides modular GitLab API client functionality:
- GitLabClient: Main unified client interface (preserves exact same API)
- BaseClient: HTTP connection and session management
- ProjectOperations: Project-related API operations  
- PipelineOperations: Pipeline-related API operations
- JobOperations: Job-related API operations
- LogProcessor: Log processing utilities
- GitLabAPIError: Exception handling (from core.exceptions)
"""

# Import main client to preserve existing import paths
from .client import GitLabClient
from ...core.exceptions import GitLabAPIError

__all__ = ["GitLabClient", "GitLabAPIError"]