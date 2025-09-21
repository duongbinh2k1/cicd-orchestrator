"""GitLab-related Pydantic models."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl


class GitLabEventType(str, Enum):
    """GitLab webhook event types."""
    PIPELINE = "Pipeline Hook"
    JOB = "Job Hook"
    PUSH = "Push Hook"
    MERGE_REQUEST = "Merge Request Hook"


class GitLabJobStatus(str, Enum):
    """GitLab job status types."""
    CREATED = "created"
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"
    SKIPPED = "skipped"
    MANUAL = "manual"


class GitLabPipelineStatus(str, Enum):
    """GitLab pipeline status types."""
    CREATED = "created"
    WAITING_FOR_RESOURCE = "waiting_for_resource"
    PREPARING = "preparing"
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"
    SKIPPED = "skipped"
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class GitLabUser(BaseModel):
    """GitLab user model."""
    id: int
    name: str
    username: str
    email: Optional[str] = None
    avatar_url: Optional[HttpUrl] = None


class GitLabNamespace(BaseModel):
    """GitLab namespace model."""
    id: int
    name: str
    path: str
    kind: str
    full_path: str
    web_url: Optional[HttpUrl] = None


class GitLabProject(BaseModel):
    """GitLab project model."""
    id: int
    name: str
    description: Optional[str] = None
    web_url: HttpUrl
    namespace: GitLabNamespace
    path_with_namespace: str
    default_branch: str = "main"
    ssh_url_to_repo: Optional[str] = None
    http_url_to_repo: Optional[HttpUrl] = None


class GitLabCommit(BaseModel):
    """GitLab commit model."""
    id: str
    message: str
    timestamp: datetime
    url: HttpUrl
    author: GitLabUser


class GitLabJob(BaseModel):
    """GitLab CI/CD job model."""
    id: int
    name: str
    stage: str
    status: GitLabJobStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration: Optional[float] = None
    user: Optional[GitLabUser] = None
    runner: Optional[Dict[str, Any]] = None
    artifacts_file: Optional[Dict[str, Any]] = None
    failure_reason: Optional[str] = None
    web_url: Optional[HttpUrl] = None
    # Project can be either full object or partial data from GitLab API
    project: Optional[Dict[str, Any]] = None
    pipeline: Optional["GitLabPipeline"] = None


class GitLabPipeline(BaseModel):
    """GitLab CI/CD pipeline model."""
    id: int
    iid: int
    status: GitLabPipelineStatus
    source: str
    ref: str
    sha: str
    before_sha: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration: Optional[int] = None
    user: Optional[GitLabUser] = None
    project: Optional[GitLabProject] = None
    commit: Optional[GitLabCommit] = None
    detailed_status: Optional[Dict[str, Any]] = None
    web_url: Optional[HttpUrl] = None


class GitLabWebhookObjectAttributes(BaseModel):
    """GitLab webhook object attributes."""
    id: int
    status: str
    stage: Optional[str] = None
    name: Optional[str] = None
    ref: Optional[str] = None
    tag: Optional[bool] = None
    sha: Optional[str] = None
    before_sha: Optional[str] = None
    source: Optional[str] = None
    created_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration: Optional[int] = None
    variables: Optional[List[Dict[str, Any]]] = None
    url: Optional[HttpUrl] = None
    failure_reason: Optional[str] = None


class GitLabWebhook(BaseModel):
    """GitLab webhook payload model."""
    object_kind: GitLabEventType
    event_type: Optional[str] = None
    user: Optional[GitLabUser] = None
    project: GitLabProject
    object_attributes: GitLabWebhookObjectAttributes
    commit: Optional[GitLabCommit] = None
    builds: Optional[List[GitLabJob]] = None
    pipeline: Optional[GitLabPipeline] = None
    repository: Optional[Dict[str, Any]] = None
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class GitLabJobLog(BaseModel):
    """GitLab job log model."""
    job_id: int
    job_name: str
    stage: str
    status: GitLabJobStatus
    log_content: str
    failure_reason: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration: Optional[float] = None
    runner_description: Optional[str] = None
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class GitLabProjectInfo(BaseModel):
    """Extended GitLab project information."""
    project: GitLabProject
    latest_pipeline: Optional[GitLabPipeline] = None
    failed_jobs: List[GitLabJob] = Field(default_factory=list)
    repository_files: Optional[List[str]] = None
    ci_config: Optional[Dict[str, Any]] = None
