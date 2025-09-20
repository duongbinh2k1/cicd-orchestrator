"""AI clients and service for analyzing CI/CD errors using various AI providers.

Architecture:
- AIService: Main service orchestrating AI analysis
- OpenAIProvider: Client for OpenAI GPT API  
- AnthropicProvider: Client for Anthropic Claude API
- BaseAIProvider: Abstract base for all AI providers/clients

This follows the pattern:
- Service = Business logic orchestrator
- Provider/Client = External API integration
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import structlog
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic

from ..core.config import settings
from ..models.ai import (
    AIAnalysisRequest,
    AIAnalysisResponse,
    AIAnalysisResult,
    AIProvider,
    AIModel,
    AIProviderConfig,
)
from ..prompts import prompt_loader

logger = structlog.get_logger(__name__)


class AIServiceError(Exception):
    """Custom exception for AI service errors."""

    def __init__(self, message: str, provider: Optional[str] = None, error_code: Optional[str] = None):
        super().__init__(message)
        self.provider = provider
        self.error_code = error_code


class BaseAIProvider:
    """Base class for AI providers."""

    def __init__(self, config: AIProviderConfig):
        self.config = config

    async def analyze_error(self, request: AIAnalysisRequest) -> AIAnalysisResponse:
        """Analyze CI/CD error using AI."""
        raise NotImplementedError

    def _build_system_prompt(self) -> str:
        """Build system prompt for CI/CD error analysis."""
        return prompt_loader.get_system_prompt()

    def _build_user_prompt(self, request: AIAnalysisRequest) -> str:
        """Build user prompt with error details using new prompt system."""
        # Prepare pipeline data
        pipeline_data = {
            'job': {
                'name': request.job_name,
                'stage': request.stage,
                'status': 'failed',  # Since we're analyzing failures
                'failure_reason': request.failure_reason,
            }
        }
        
        # Prepare GitLab data if available
        gitlab_data = {}
        if request.project_context:
            gitlab_data['project_info'] = request.project_context
        if request.ci_config:
            gitlab_data['ci_config'] = request.ci_config
        if request.repository_files:
            gitlab_data['repository_files'] = [{'name': f} for f in request.repository_files]
        
        # Use the new prompt system to build the complete prompt
        prompt = prompt_loader.build_analysis_prompt(
            pipeline_data=pipeline_data,
            gitlab_data=gitlab_data if gitlab_data else None,
            error_context=request.job_log
        )
        
        # Add custom prompt if provided
        if request.custom_prompt:
            prompt += f"\n\n## Additional Instructions\n{request.custom_prompt}"
        
        return prompt


class OpenAIProvider(BaseAIProvider):
    """OpenAI GPT provider for CI/CD error analysis."""

    def __init__(self, config: AIProviderConfig):
        super().__init__(config)
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )

    def _create_mock_response(self, request: AIAnalysisRequest, request_id: str, start_time: float) -> AIAnalysisResponse:
        """Create mock response for development."""
        processing_time = int((time.time() - start_time) * 1000)
        
        mock_results = [
            AIAnalysisResult(
                category="Configuration",
                severity="medium",
                title="Mock Analysis Result",
                description="This is a mock response for development testing",
                solution="Configure proper AI provider credentials",
                confidence_score=0.8
            )
        ]
        
        return AIAnalysisResponse(
            request_id=request_id,
            analysis_type=request.analysis_type,
            provider=AIProvider.OPENAI,
            model="mock-model",
            created_at=datetime.utcnow(),
            processing_time_ms=processing_time,
            summary="Mock analysis for development - configure real AI provider",
            severity_level="info",
            confidence_score=0.8,
            results=mock_results,
            immediate_actions=["Configure real AI provider API key"],
            preventive_measures=["Set up proper environment variables"],
            tags=["mock", "development"],
            raw_response={"mock": True}
        )

    async def analyze_error(self, request: AIAnalysisRequest) -> AIAnalysisResponse:
        """Analyze error using OpenAI GPT."""
        start_time = time.time()
        request_id = str(uuid.uuid4())

        # Development fallback when no real API key
        if self.config.api_key in ["your-openai-api-key-here", "sk-or-v1-your-openrouter-api-key-here"]:
            logger.warning("Using mock AI response - no real API key configured")
            return self._create_mock_response(request, request_id, start_time)

        try:
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_user_prompt(request)

            model = request.model or self.config.model
            temperature = request.temperature
            max_tokens = request.max_tokens

            logger.info(
                "Sending request to OpenAI",
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                request_id=request_id,
            )

            response = await self.client.chat.completions.create(
                model=model.value if hasattr(model, 'value') else str(model),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )

            processing_time = int((time.time() - start_time) * 1000)

            # Parse the response
            response_content = response.choices[0].message.content
            ai_response_data = json.loads(response_content)

            # Create analysis results
            results = []
            for result_data in ai_response_data.get("results", []):
                results.append(AIAnalysisResult(**result_data))

            return AIAnalysisResponse(
                request_id=request_id,
                analysis_type=request.analysis_type,
                provider=AIProvider.OPENAI,
                model=str(model),
                created_at=datetime.utcnow(),
                processing_time_ms=processing_time,
                summary=ai_response_data.get("summary", ""),
                root_cause=ai_response_data.get("root_cause"),
                severity_level=ai_response_data.get("severity_level", "medium"),
                confidence_score=ai_response_data.get("confidence_score", 0.5),
                results=results,
                immediate_actions=ai_response_data.get("immediate_actions", []),
                preventive_measures=ai_response_data.get("preventive_measures", []),
                related_issues=ai_response_data.get("related_issues"),
                tags=ai_response_data.get("tags", []),
                tokens_used=response.usage.total_tokens if response.usage else None,
                estimated_cost=self._calculate_cost(response.usage) if response.usage else None,
                raw_response={
                    "id": response.id,
                    "choices": [choice.model_dump() for choice in response.choices],
                    "usage": response.usage.model_dump() if response.usage else None,
                },
            )

        except json.JSONDecodeError as e:
            logger.error("Failed to parse OpenAI response as JSON", error=str(e))
            raise AIServiceError(f"Invalid JSON response from OpenAI: {e}", provider="openai")

        except Exception as e:
            logger.error("OpenAI API error", error=str(e))
            raise AIServiceError(f"OpenAI API error: {e}", provider="openai")

    def _calculate_cost(self, usage) -> float:
        """Calculate estimated cost based on token usage."""
        # OpenAI pricing (as of 2024) - update as needed
        pricing = {
            "gpt-4-turbo-preview": {"input": 0.01, "output": 0.03},
            "gpt-4": {"input": 0.03, "output": 0.06},
            "gpt-3.5-turbo": {"input": 0.0015, "output": 0.002},
        }

        model_key = str(self.config.model).replace("AIModel.", "").lower()
        if model_key not in pricing:
            return 0.0

        input_cost = (usage.prompt_tokens / 1000) * pricing[model_key]["input"]
        output_cost = (usage.completion_tokens / 1000) * pricing[model_key]["output"]

        return input_cost + output_cost


class AnthropicProvider(BaseAIProvider):
    """Anthropic Claude provider for CI/CD error analysis."""

    def __init__(self, config: AIProviderConfig):
        super().__init__(config)
        self.client = AsyncAnthropic(
            api_key=config.api_key,
            timeout=config.timeout_seconds,
        )

    async def analyze_error(self, request: AIAnalysisRequest) -> AIAnalysisResponse:
        """Analyze error using Anthropic Claude."""
        start_time = time.time()
        request_id = f"anthropic_{int(start_time * 1000)}"

        try:
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_user_prompt(request)

            model = request.model or self.config.model
            max_tokens = request.max_tokens or 2000

            logger.info(
                "Sending request to Anthropic",
                model=model,
                max_tokens=max_tokens,
                request_id=request_id,
            )

            response = await self.client.messages.create(
                model=model.value if hasattr(model, 'value') else str(model),
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=max_tokens,
                temperature=request.temperature,
            )

            processing_time = int((time.time() - start_time) * 1000)

            # Parse the response
            response_content = response.content[0].text
            ai_response_data = json.loads(response_content)

            # Create analysis results
            results = []
            for result_data in ai_response_data.get("results", []):
                results.append(AIAnalysisResult(**result_data))

            return AIAnalysisResponse(
                request_id=request_id,
                analysis_type=request.analysis_type,
                provider=AIProvider.ANTHROPIC,
                model=str(model),
                created_at=datetime.utcnow(),
                processing_time_ms=processing_time,
                summary=ai_response_data.get("summary", ""),
                root_cause=ai_response_data.get("root_cause"),
                severity_level=ai_response_data.get("severity_level", "medium"),
                confidence_score=ai_response_data.get("confidence_score", 0.5),
                results=results,
                immediate_actions=ai_response_data.get("immediate_actions", []),
                preventive_measures=ai_response_data.get("preventive_measures", []),
                related_issues=ai_response_data.get("related_issues"),
                tags=ai_response_data.get("tags", []),
                tokens_used=response.usage.input_tokens + response.usage.output_tokens if response.usage else None,
                estimated_cost=self._calculate_cost(response.usage) if response.usage else None,
                raw_response={
                    "id": response.id,
                    "content": [content.model_dump() for content in response.content],
                    "usage": response.usage.model_dump() if response.usage else None,
                },
            )

        except json.JSONDecodeError as e:
            logger.error("Failed to parse Anthropic response as JSON", error=str(e))
            raise AIServiceError(f"Invalid JSON response from Anthropic: {e}", provider="anthropic")

        except Exception as e:
            logger.error("Anthropic API error", error=str(e))
            raise AIServiceError(f"Anthropic API error: {e}", provider="anthropic")

    def _calculate_cost(self, usage) -> float:
        """Calculate estimated cost based on token usage."""
        # Anthropic pricing (as of 2024) - update as needed
        pricing = {
            "claude-3-opus": {"input": 0.015, "output": 0.075},
            "claude-3-sonnet": {"input": 0.003, "output": 0.015},
            "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
        }

        model_key = str(self.config.model).replace("AIModel.", "").lower().replace("-", "_")
        if model_key not in pricing:
            return 0.0

        input_cost = (usage.input_tokens / 1000) * pricing[model_key]["input"]
        output_cost = (usage.output_tokens / 1000) * pricing[model_key]["output"]

        return input_cost + output_cost


class AIService:
    """Main AI service for managing multiple AI providers."""

    def __init__(self):
        self.providers: Dict[AIProvider, BaseAIProvider] = {}
        self._initialize_providers()

    def _initialize_providers(self):
        """Initialize available AI providers."""
        # OpenAI
        if settings.openai_api_key:
            openai_config = AIProviderConfig(
                provider=AIProvider.OPENAI,
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=AIModel.GPT_4_TURBO,
                default_temperature=settings.openai_temperature,
                default_max_tokens=settings.openai_max_tokens,
                timeout_seconds=60,
            )
            self.providers[AIProvider.OPENAI] = OpenAIProvider(openai_config)

        # Anthropic Claude
        if settings.anthropic_api_key:
            anthropic_config = AIProviderConfig(
                provider=AIProvider.ANTHROPIC,
                api_key=settings.anthropic_api_key,
                model=AIModel.CLAUDE_3_SONNET,
                default_temperature=settings.anthropic_temperature,
                default_max_tokens=settings.anthropic_max_tokens,
                timeout_seconds=60,
            )
            self.providers[AIProvider.ANTHROPIC] = AnthropicProvider(anthropic_config)

        if not self.providers:
            logger.warning("No AI providers configured")

    async def analyze_error(
        self, 
        request: AIAnalysisRequest,
        fallback_providers: Optional[List[AIProvider]] = None
    ) -> AIAnalysisResponse:
        """Analyze CI/CD error using specified provider with fallback options.
        
        Args:
            request: Analysis request
            fallback_providers: List of fallback providers to try if primary fails
            
        Returns:
            Analysis response
            
        Raises:
            AIServiceError: When all providers fail
        """
        # Primary provider
        primary_provider = request.provider
        providers_to_try = [primary_provider]
        
        # Add fallback providers
        if fallback_providers:
            providers_to_try.extend(fallback_providers)
        else:
            # Default fallbacks
            all_providers = list(self.providers.keys())
            for provider in all_providers:
                if provider != primary_provider:
                    providers_to_try.append(provider)

        last_error = None
        
        for provider in providers_to_try:
            if provider not in self.providers:
                logger.warning(f"Provider {provider} not available")
                continue
                
            try:
                logger.info(f"Attempting analysis with provider {provider}")
                
                # Update request provider for current attempt
                current_request = request.model_copy()
                current_request.provider = provider
                
                result = await self.providers[provider].analyze_error(current_request)
                logger.info(f"Successfully analyzed with provider {provider}")
                return result
                
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Provider {provider} failed",
                    error=str(e),
                    provider=provider
                )
                continue

        # All providers failed
        raise AIServiceError(
            f"All AI providers failed. Last error: {last_error}",
            error_code="all_providers_failed"
        )

    async def health_check(self) -> Dict[AIProvider, bool]:
        """Check health of all configured AI providers.
        
        Returns:
            Dictionary mapping providers to their health status
        """
        health_status = {}
        
        for provider_type, provider in self.providers.items():
            try:
                # Create a simple test request
                test_request = AIAnalysisRequest(
                    analysis_type="error_diagnosis",
                    job_log="echo 'test'",
                    job_name="health_check",
                    stage="test",
                    provider=provider_type,
                    max_tokens=100,
                )
                
                # Set a short timeout for health check
                result = await asyncio.wait_for(
                    provider.analyze_error(test_request),
                    timeout=10.0
                )
                health_status[provider_type] = True
                
            except Exception as e:
                logger.warning(f"Health check failed for {provider_type}", error=str(e))
                health_status[provider_type] = False
        
        return health_status

    def get_available_providers(self) -> List[AIProvider]:
        """Get list of available AI providers."""
        return list(self.providers.keys())

    def is_provider_available(self, provider: AIProvider) -> bool:
        """Check if a specific provider is available."""
        return provider in self.providers
