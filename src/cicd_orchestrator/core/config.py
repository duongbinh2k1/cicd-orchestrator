"""Application configuration using Pydantic Settings."""

import os
from functools import lru_cache
from typing import List, Optional

from pydantic import Field, validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    # Application
    app_name: str = "CI/CD Orchestrator"
    app_version: str = "0.1.0"
    debug: bool = Field(default=False, env="DEBUG")
    environment: str = Field(default="development", env="ENVIRONMENT")
    
    # Server
    host: str = Field(default="0.0.0.0", env="HOST")
    port: int = Field(default=8000, env="PORT")
    reload: bool = Field(default=False, env="RELOAD")
    
    # Security
    secret_key: str = Field(default="dev-secret-key-change-in-production", env="SECRET_KEY")
    allowed_hosts: str = Field(default="*", env="ALLOWED_HOSTS")
    cors_origins: str = Field(default="*", env="CORS_ORIGINS")
    
    # GitLab Integration
    gitlab_api_token: str = Field(default="your-gitlab-token-here", env="GITLAB_API_TOKEN")
    gitlab_base_url: str = Field(default="https://gitlab.com", env="GITLAB_BASE_URL")
    gitlab_webhook_secret: Optional[str] = Field(default=None, env="GITLAB_WEBHOOK_SECRET")
    
    # GitLab Data Fetching Strategy
    gitlab_auto_fetch_logs: bool = Field(default=True, env="GITLAB_AUTO_FETCH_LOGS")
    gitlab_fetch_strategy: str = Field(default="smart", env="GITLAB_FETCH_STRATEGY")
    gitlab_fetch_full_pipeline: bool = Field(default=True, env="GITLAB_FETCH_FULL_PIPELINE")
    gitlab_fetch_project_info: bool = Field(default=True, env="GITLAB_FETCH_PROJECT_INFO")
    gitlab_fetch_ci_config: bool = Field(default=True, env="GITLAB_FETCH_CI_CONFIG")
    gitlab_fetch_recent_commits: bool = Field(default=True, env="GITLAB_FETCH_RECENT_COMMITS")
    gitlab_log_lines_limit: int = Field(default=2000, env="GITLAB_LOG_LINES_LIMIT")
    gitlab_api_timeout: int = Field(default=30, env="GITLAB_API_TIMEOUT")
    gitlab_max_retries: int = Field(default=3, env="GITLAB_MAX_RETRIES")
    
    # AI Providers
    default_ai_provider: str = Field(default="openai", env="DEFAULT_AI_PROVIDER")
    
    # OpenAI (including OpenRouter)
    openai_api_key: Optional[str] = Field(default=None, env="OPENAI_API_KEY")
    openai_base_url: Optional[str] = Field(default=None, env="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-3.5-turbo", env="OPENAI_MODEL")
    openai_temperature: float = Field(default=0.3, env="OPENAI_TEMPERATURE")
    openai_max_tokens: int = Field(default=2000, env="OPENAI_MAX_TOKENS")
    
    # Anthropic Claude
    anthropic_api_key: Optional[str] = Field(default=None, env="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-3-sonnet-20240229", env="ANTHROPIC_MODEL")
    anthropic_temperature: float = Field(default=0.3, env="ANTHROPIC_TEMPERATURE")
    anthropic_max_tokens: int = Field(default=2000, env="ANTHROPIC_MAX_TOKENS")
    
    # Logging
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_format: str = Field(default="console", env="LOG_FORMAT")  # json or console
    log_file: Optional[str] = Field(default=None, env="LOG_FILE")
    
    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://cicd_user:cicd_password@localhost:5432/cicd_orchestrator",
        env="DATABASE_URL"
    )
    database_echo: bool = Field(default=False, env="DATABASE_ECHO")
    
    # Processing settings
    max_concurrent_analysis: int = Field(default=3, env="MAX_CONCURRENT_ANALYSIS")
    analysis_timeout: int = Field(default=300, env="ANALYSIS_TIMEOUT")
    
    @validator("gitlab_api_token", pre=True, always=True)
    def validate_gitlab_token(cls, v):
        """Validate GitLab API token - optional for development."""
        if v in ["your-gitlab-token-here", None, ""]:
            return "dev-token-placeholder"
        return v

    @validator("log_level")
    def validate_log_level(cls, v):
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return v.upper()
    
    @validator("log_format")
    def validate_log_format(cls, v):
        """Validate log format."""
        valid_formats = ["json", "console"]
        if v.lower() not in valid_formats:
            raise ValueError(f"Log format must be one of: {valid_formats}")
        return v.lower()

    class Config:
        """Pydantic configuration."""
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get application settings (cached)."""
    return Settings()


# Global settings instance
settings = get_settings()
