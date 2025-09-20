"""Orchestrator-related Pydantic models."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .ai import AIAnalysisResponse
from .gitlab import GitLabWebhook, GitLabJobLog, GitLabProjectInfo


class OrchestrationStatus(str, Enum):
    """Orchestration process status."""
    PENDING = "pending"
    PROCESSING = "processing"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class ErrorSeverity(str, Enum):
    """Error severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ErrorCategory(str, Enum):
    """Error category types."""
    BUILD_FAILURE = "build_failure"
    TEST_FAILURE = "test_failure"
    DEPLOYMENT_FAILURE = "deployment_failure"
    DEPENDENCY_ISSUE = "dependency_issue"
    CONFIGURATION_ERROR = "configuration_error"
    INFRASTRUCTURE_ISSUE = "infrastructure_issue"
    SECURITY_ISSUE = "security_issue"
    PERFORMANCE_ISSUE = "performance_issue"
    CODE_QUALITY = "code_quality"
    UNKNOWN = "unknown"


class OrchestrationRequest(BaseModel):
    """Request model for orchestration process."""
    webhook_data: GitLabWebhook
    priority: int = Field(default=5, ge=1, le=10)
    custom_analysis_prompt: Optional[str] = None
    include_context: bool = True
    include_repository_files: bool = False
    max_analysis_depth: int = Field(default=3, ge=1, le=5)
    timeout_seconds: int = Field(default=300, gt=0)
    
    class Config:
        """Pydantic configuration."""
        arbitrary_types_allowed = True


class ErrorAnalysis(BaseModel):
    """Comprehensive error analysis result."""
    category: ErrorCategory
    severity: ErrorSeverity
    title: str
    description: str
    root_cause: Optional[str] = None
    affected_components: List[str] = Field(default_factory=list)
    
    # Solutions and recommendations
    immediate_fixes: List[str] = Field(default_factory=list)
    long_term_solutions: List[str] = Field(default_factory=list)
    preventive_measures: List[str] = Field(default_factory=list)
    
    # Code-related suggestions
    code_changes: Optional[List[Dict[str, str]]] = None
    configuration_changes: Optional[List[Dict[str, str]]] = None
    
    # Additional context
    related_documentation: List[str] = Field(default_factory=list)
    similar_issues: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    
    # Confidence and metadata
    confidence_score: float = Field(ge=0.0, le=1.0)
    analysis_duration_ms: int
    ai_provider_used: str


class OrchestrationResponse(BaseModel):
    """Response model for orchestration process."""
    request_id: str
    status: OrchestrationStatus
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    
    # Request context
    project_id: int
    pipeline_id: int
    failed_job_ids: List[int] = Field(default_factory=list)
    
    # Analysis results
    error_analysis: Optional[ErrorAnalysis] = None
    ai_analysis: Optional[AIAnalysisResponse] = None
    
    # Retrieved data
    job_logs: List[GitLabJobLog] = Field(default_factory=list)
    project_info: Optional[GitLabProjectInfo] = None
    
    # Processing metadata
    processing_steps: List[str] = Field(default_factory=list)
    total_processing_time_ms: int = 0
    error_message: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    
    # Actions and feedback  
    suggested_actions: List[str] = Field(default_factory=list)
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class OrchestrationStats(BaseModel):
    """Statistics for orchestration processes."""
    total_requests: int = 0
    successful_analyses: int = 0
    failed_analyses: int = 0
    average_processing_time_ms: float = 0.0
    
    # Error category breakdown
    error_categories: Dict[ErrorCategory, int] = Field(default_factory=dict)
    severity_distribution: Dict[ErrorSeverity, int] = Field(default_factory=dict)
    
    # Time-based metrics
    requests_last_24h: int = 0
    requests_last_7d: int = 0
    requests_last_30d: int = 0
    
    # Performance metrics
    fastest_analysis_ms: Optional[int] = None
    slowest_analysis_ms: Optional[int] = None
    timeout_rate: float = 0.0
    
    # AI provider usage
    ai_provider_usage: Dict[str, int] = Field(default_factory=dict)
    total_ai_costs: float = 0.0
    
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
