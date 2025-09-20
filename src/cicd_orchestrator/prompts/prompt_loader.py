"""
Prompt loader and formatter for dynamic prompt management.
Version: 1.0
"""

import os
from typing import Dict, Optional
from .base_system import BASE_SYSTEM_PROMPT
from .error_templates import ERROR_TEMPLATES
from .context_builders import (
    build_project_context,
    build_ci_config_context,
    build_environment_context,
    build_error_context,
    build_repository_files_context
)


class PromptLoader:
    """Manages loading and formatting of prompts with dynamic context."""
    
    def __init__(self):
        self.base_prompt = BASE_SYSTEM_PROMPT
        self.error_templates = ERROR_TEMPLATES
    
    def get_system_prompt(self) -> str:
        """Get the base system prompt."""
        return self.base_prompt
    
    def get_error_template(self, error_type: str) -> str:
        """Get error template by type."""
        return self.error_templates.get(error_type, self.error_templates['generic'])
    
    def build_analysis_prompt(
        self,
        pipeline_data: Dict,
        gitlab_data: Optional[Dict] = None,
        error_context: Optional[str] = None
    ) -> str:
        """
        Build complete analysis prompt with context.
        
        Args:
            pipeline_data: Pipeline and job information
            gitlab_data: Additional GitLab context (project info, CI config, etc.)
            error_context: Specific error context if available
        
        Returns:
            Formatted prompt string
        """
        prompt_parts = [self.base_prompt]
        
        # Add pipeline context
        pipeline_context = self._build_pipeline_context(pipeline_data)
        prompt_parts.append(f"\n## Pipeline Context\n{pipeline_context}")
        
        # Add GitLab project context if available
        if gitlab_data:
            if gitlab_data.get('project_info'):
                project_context = build_project_context(gitlab_data['project_info'])
                prompt_parts.append(f"\n## Project Context\n{project_context}")
            
            if gitlab_data.get('ci_config'):
                ci_context = build_ci_config_context(gitlab_data['ci_config'])
                prompt_parts.append(f"\n## CI/CD Configuration\n{ci_context}")
            
            if gitlab_data.get('repository_files'):
                files_context = build_repository_files_context(gitlab_data['repository_files'])
                prompt_parts.append(f"\n## Repository Structure\n{files_context}")
        
        # Add error-specific template if we can determine error type
        error_type = self._detect_error_type(pipeline_data)
        if error_type:
            error_template = self.get_error_template(error_type)
            prompt_parts.append(f"\n## Error Analysis Guidelines\n{error_template}")
        
        # Add environment-specific context
        if 'job' in pipeline_data:
            job = pipeline_data['job']
            stage = job.get('stage', 'unknown')
            job_name = job.get('name', 'unknown')
            env_context = build_environment_context(stage, job_name)
            prompt_parts.append(f"\n## Environment Context\n{env_context}")
        
        # Add specific error context if provided
        if error_context:
            formatted_error_context = build_error_context(error_context)
            prompt_parts.append(f"\n## Error Details\n{formatted_error_context}")
        
        # Add analysis request
        prompt_parts.append(self._build_analysis_request(pipeline_data))
        
        return "\n".join(prompt_parts)
    
    def _build_pipeline_context(self, pipeline_data: Dict) -> str:
        """Build pipeline-specific context."""
        context_parts = []
        
        if 'pipeline' in pipeline_data:
            pipeline = pipeline_data['pipeline']
            context_parts.extend([
                f"Pipeline ID: {pipeline.get('id')}",
                f"Status: {pipeline.get('status')}",
                f"Branch/Tag: {pipeline.get('ref')}",
                f"Source: {pipeline.get('source')}",
                f"Created: {pipeline.get('created_at')}",
            ])
            
            if pipeline.get('user'):
                context_parts.append(f"Triggered by: {pipeline['user'].get('name', 'Unknown')}")
        
        if 'job' in pipeline_data:
            job = pipeline_data['job']
            context_parts.extend([
                f"\nJob: {job.get('name')}",
                f"Stage: {job.get('stage')}",
                f"Status: {job.get('status')}",
                f"Duration: {job.get('duration', 'Unknown')}s",
            ])
            
            if job.get('failure_reason'):
                context_parts.append(f"Failure Reason: {job['failure_reason']}")
        
        return "\n".join(context_parts)
    
    def _detect_error_type(self, pipeline_data: Dict) -> Optional[str]:
        """Detect the type of error based on pipeline data."""
        if 'job' not in pipeline_data:
            return None
        
        job = pipeline_data['job']
        stage = job.get('stage', '').lower()
        job_name = job.get('name', '').lower()
        failure_reason = job.get('failure_reason', '').lower()
        
        # Check by stage
        if 'build' in stage or 'compile' in stage:
            return 'build'
        elif 'test' in stage:
            return 'test'
        elif 'deploy' in stage or 'release' in stage:
            return 'deploy'
        
        # Check by job name
        if any(keyword in job_name for keyword in ['build', 'compile', 'make']):
            return 'build'
        elif any(keyword in job_name for keyword in ['test', 'spec', 'check']):
            return 'test'
        elif any(keyword in job_name for keyword in ['deploy', 'release', 'publish']):
            return 'deploy'
        
        # Check by failure reason
        if any(keyword in failure_reason for keyword in ['script_failure', 'build']):
            return 'build'
        elif 'test' in failure_reason:
            return 'test'
        
        return 'generic'
    
    def _build_analysis_request(self, pipeline_data: Dict) -> str:
        """Build the final analysis request."""
        return """
## Analysis Request

Based on the above context, please analyze the CI/CD pipeline failure and provide:

1. **Root Cause Analysis**: What exactly went wrong?
2. **Impact Assessment**: How does this affect the project?
3. **Recommended Actions**: Specific steps to fix the issue
4. **Prevention Strategies**: How to avoid similar issues in the future

Please format your response as valid JSON according to the schema defined in the system prompt above.
"""


# Global instance
prompt_loader = PromptLoader()
