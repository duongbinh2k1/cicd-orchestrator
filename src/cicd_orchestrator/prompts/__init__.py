"""
Prompt management module for CI/CD Orchestrator.

This module provides:
- Base system prompts for AI analysis
- Specialized error templates for different failure types  
- Context builders for enriching prompts with GitLab data
- Dynamic prompt loader for flexible prompt management

Usage:
    from cicd_orchestrator.prompts import prompt_loader
    
    # Build analysis prompt with context
    prompt = prompt_loader.build_analysis_prompt(
        pipeline_data=pipeline_info,
        gitlab_data=additional_context
    )
"""

from .prompt_loader import prompt_loader, PromptLoader
from .base_system import BASE_SYSTEM_PROMPT
from .error_templates import ERROR_TEMPLATES
from .context_builders import (
    build_project_context,
    build_ci_config_context, 
    build_environment_context,
    build_error_context,
    build_repository_files_context
)

__all__ = [
    'prompt_loader',
    'PromptLoader', 
    'BASE_SYSTEM_PROMPT',
    'ERROR_TEMPLATES',
    'build_project_context',
    'build_ci_config_context',
    'build_environment_context', 
    'build_error_context',
    'build_repository_files_context'
]
