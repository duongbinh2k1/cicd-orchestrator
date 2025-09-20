"""AI service-related Pydantic models."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AIProvider(str, Enum):
    """Supported AI providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE_OPENAI = "azure_openai"
    GEMINI = "gemini"
    OLLAMA = "ollama"


class AIModel(str, Enum):
    """AI model types."""
    # OpenAI models
    GPT_4_TURBO = "gpt-4-turbo-preview"
    GPT_4 = "gpt-4"
    GPT_3_5_TURBO = "gpt-3.5-turbo"
    
    # Anthropic models
    CLAUDE_3_OPUS = "claude-3-opus-20240229"
    CLAUDE_3_SONNET = "claude-3-sonnet-20240229"
    CLAUDE_3_HAIKU = "claude-3-haiku-20240307"
    
    # Google models
    GEMINI_PRO = "gemini-pro"
    GEMINI_PRO_VISION = "gemini-pro-vision"


class AIAnalysisType(str, Enum):
    """Types of AI analysis."""
    ERROR_DIAGNOSIS = "error_diagnosis"
    SOLUTION_SUGGESTION = "solution_suggestion"
    CODE_REVIEW = "code_review"
    PERFORMANCE_OPTIMIZATION = "performance_optimization"
    SECURITY_ANALYSIS = "security_analysis"


class AIAnalysisRequest(BaseModel):
    """Request model for AI analysis."""
    analysis_type: AIAnalysisType
    job_log: str
    job_name: str
    stage: str
    failure_reason: Optional[str] = None
    project_context: Optional[Dict[str, Any]] = None
    ci_config: Optional[Dict[str, Any]] = None
    repository_files: Optional[List[str]] = None
    previous_analyses: Optional[List["AIAnalysisResponse"]] = None
    custom_prompt: Optional[str] = None
    provider: AIProvider = AIProvider.OPENAI
    model: Optional[AIModel] = None
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=2000, gt=0, le=8000)
    
    class Config:
        """Pydantic configuration."""
        use_enum_values = True


class AIAnalysisResult(BaseModel):
    """Individual analysis result."""
    category: str
    severity: str  # critical, high, medium, low
    title: str
    description: str
    solution: str
    code_examples: Optional[List[str]] = None
    documentation_links: Optional[List[str]] = None
    confidence_score: float = Field(ge=0.0, le=1.0)


class AIAnalysisResponse(BaseModel):
    """Response model for AI analysis."""
    request_id: str
    analysis_type: AIAnalysisType
    provider: AIProvider
    model: str
    created_at: datetime
    processing_time_ms: int
    
    # Analysis results
    summary: str
    root_cause: Optional[str] = None
    severity_level: str  # critical, high, medium, low, info
    confidence_score: float = Field(ge=0.0, le=1.0)
    
    # Detailed findings
    results: List[AIAnalysisResult] = Field(default_factory=list)
    
    # Recommendations
    immediate_actions: List[str] = Field(default_factory=list)
    preventive_measures: List[str] = Field(default_factory=list)
    
    # Additional context
    related_issues: Optional[List[str]] = None
    tags: List[str] = Field(default_factory=list)
    
    # Token usage information
    tokens_used: Optional[int] = None
    estimated_cost: Optional[float] = None
    
    # Raw response from AI provider
    raw_response: Optional[Dict[str, Any]] = None
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class AIProviderConfig(BaseModel):
    """Configuration for AI providers."""
    provider: AIProvider
    api_key: str
    base_url: Optional[str] = None
    model: AIModel
    default_temperature: float = 0.3
    default_max_tokens: int = 2000
    timeout_seconds: int = 60
    rate_limit_per_minute: Optional[int] = None
    
    class Config:
        """Pydantic configuration."""
        use_enum_values = True


class AIAnalysisHistory(BaseModel):
    """Historical AI analysis data."""
    id: str
    project_id: int
    pipeline_id: int
    job_id: int
    analysis_request: AIAnalysisRequest
    analysis_response: AIAnalysisResponse
    feedback_rating: Optional[int] = Field(None, ge=1, le=5)
    feedback_comment: Optional[str] = None
    was_helpful: Optional[bool] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
