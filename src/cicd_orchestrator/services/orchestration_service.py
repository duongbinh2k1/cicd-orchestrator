"""Orchestration service for managing CI/CD error analysis workflow."""

import asyncio
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from imap_tools import AND

from ..core.config import settings
from ..core.exceptions import (
    OrchestrationError,
    AnalysisTimeoutError,
    GitLabAPIError,
    AIServiceError,
)
from ..models.ai import AIAnalysisRequest, AIAnalysisType, AIProvider
from ..models.gitlab import GitLabJobLog, GitLabProjectInfo
from ..models.email import ProcessedEmail
from ..models.orchestrator import (
    OrchestrationRequest,
    OrchestrationResponse,
    OrchestrationStatus,
    ErrorAnalysis,
    ErrorCategory,
    ErrorSeverity,
)
from .gitlab_client import GitLabClient
from .ai_service import AIService

logger = structlog.get_logger(__name__)


class OrchestrationService:
    """Main orchestration service for CI/CD error analysis."""

    def __init__(self, db: AsyncSession):
        self.ai_service = AIService()
        self.db = db
        self._active_analyses: Dict[str, OrchestrationResponse] = {}
        # Email monitoring state
        self._email_monitoring_task: Optional[asyncio.Task] = None
        self._email_monitoring_running = False
        self._last_email_check: Optional[datetime] = None

    async def start_email_monitoring(self):
        """Start email monitoring as part of orchestration."""
        if self._email_monitoring_running:
            logger.warning("Email monitoring already running")
            return
            
        if not settings.imap_enabled:
            logger.warning("Email monitoring is disabled", imap_enabled=False)
            return
            
        self._email_monitoring_running = True
        self._email_monitoring_task = asyncio.create_task(self._email_monitoring_loop())
        
        logger.info(
            "Orchestrator started email monitoring",
            server=settings.imap_server,
            user=settings.imap_user,
            check_interval=settings.imap_check_interval
        )

    async def stop_email_monitoring(self):
        """Stop email monitoring."""
        self._email_monitoring_running = False
        if self._email_monitoring_task:
            self._email_monitoring_task.cancel()
            try:
                await self._email_monitoring_task
            except asyncio.CancelledError:
                pass
        logger.info("Orchestrator stopped email monitoring")

    async def _email_monitoring_loop(self):
        """Main email monitoring loop controlled by orchestrator."""
        while self._email_monitoring_running:
            try:
                await self._check_and_process_emails()
                await asyncio.sleep(settings.imap_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "Error in orchestrator email monitoring loop",
                    error=str(e),
                    exc_info=True
                )
                # Continue monitoring despite errors
                await asyncio.sleep(60)  # Wait before retrying

    async def _check_and_process_emails(self):
        """Check for new emails and process them through orchestration."""
        try:
            from .email_service import EmailUtils
            
            logger.debug("Orchestrator checking for new emails")
            
            # Calculate date range for fetching emails
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
            
            with EmailUtils.get_imap_connection() as mailbox:
                # Search for emails from GitLab in the last week with failure keywords in subject
                gitlab_email = settings.imap_gitlab_email
                
                if not gitlab_email:
                    logger.warning("IMAP_GITLAB_EMAIL not configured, skipping email check")
                    return
                
                # Simple IMAP search: FROM GitLab AND since last week
                search_query = f'FROM "{gitlab_email}" SINCE {week_ago}'
                
                logger.debug(
                    "Searching for emails",
                    query=search_query,
                    gitlab_email=gitlab_email,
                    week_ago=week_ago
                )
                
                email_count = 0
                processed_count = 0
                
                for msg in mailbox.fetch(
                    search_query,
                    mark_seen=False  # Don't mark as read yet
                ):
                    email_count += 1
                    logger.debug(
                        "Found email",
                        subject=getattr(msg, 'subject', 'unknown'),
                        from_email=getattr(msg, 'from_', 'unknown'),
                        uid=getattr(msg, 'uid', 'unknown')
                    )
                    
                    # Additional filtering for failure keywords in subject (done in code)
                    is_valid, validation_error = EmailUtils.validate_email_for_processing(msg)
                    if not is_valid:
                        logger.debug(
                            "Email validation failed",
                            validation_error=validation_error,
                            subject=getattr(msg, 'subject', 'unknown')
                        )
                        continue
                        
                    try:
                        await self._process_email_message(msg)
                        processed_count += 1
                    except Exception as e:
                        logger.error(
                            "Orchestrator failed to process email",
                            message_id=getattr(msg, 'message_id', 'unknown'),
                            error=str(e),
                            exc_info=True
                        )
                
                logger.debug(
                    "Email processing completed",
                    total_found=email_count,
                    processed=processed_count
                )
                        
        except Exception as e:
            logger.error(
                "Orchestrator error checking emails",
                error=str(e),
                exc_info=True
            )

    async def _process_email_message(self, msg):
        """Process individual email message through orchestration workflow."""
        from .email_service import EmailUtils
        
        try:
            # Check if we've already processed this message
            if await self._is_email_already_processed(msg):
                logger.debug(
                    "Email already processed",
                    message_id=getattr(msg, 'message_id', msg.uid)
                )
                return

            # Create database record
            processed_email = EmailUtils.create_processed_email_record(msg)
            self.db.add(processed_email)
            await self.db.commit()

            # Extract GitLab headers
            gitlab_headers, error_msg = EmailUtils.extract_gitlab_headers(msg)
            
            if not gitlab_headers:
                processed_email.status = "no_gitlab_headers"
                processed_email.error_message = error_msg
                await self.db.commit()
                
                logger.warning(
                    "No GitLab headers found in email",
                    subject=msg.subject,
                    from_email=msg.from_,
                    error=error_msg
                )
                return

            # Update processed email with GitLab data
            processed_email.project_id = gitlab_headers["project_id"]
            processed_email.project_name = gitlab_headers["project_name"]
            processed_email.project_path = gitlab_headers["project_path"]
            processed_email.pipeline_id = gitlab_headers["pipeline_id"]
            processed_email.pipeline_ref = gitlab_headers["pipeline_ref"]
            processed_email.pipeline_status = gitlab_headers["pipeline_status"]
            
            # Store email content
            if msg.html:
                processed_email.error_message = msg.html
            elif msg.text:
                processed_email.error_message = msg.text
            
            processed_email.status = "processing_pipeline"
            await self.db.commit()

            # Create webhook data and orchestrate processing
            webhook_data = EmailUtils.create_webhook_from_email(msg, gitlab_headers)
            request = OrchestrationRequest(
                webhook_data=webhook_data,
                include_context=True
            )
            
            # Process through orchestration pipeline
            try:
                orchestration_result = await self.process_webhook(request)
                
                # Store orchestration results back to email record
                if orchestration_result.error_analysis:
                    analysis = orchestration_result.error_analysis
                    
                    # Create comprehensive analysis summary
                    analysis_summary = f"""
=== AI ANALYSIS RESULTS ===
Category: {analysis.category.value}
Severity: {analysis.severity.value}
Confidence: {analysis.confidence_score:.2f}

Root Cause:
{analysis.root_cause or 'Not identified'}

Recommendations:
{chr(10).join([f"- {rec}" for rec in analysis.recommendations])}

Processing Details:
- Request ID: {orchestration_result.request_id}
- Processing Time: {orchestration_result.total_processing_time_ms}ms
- Status: {orchestration_result.status.value}

=== ORIGINAL EMAIL CONTENT ===
{processed_email.error_message or 'No email content'}
"""
                    processed_email.error_message = analysis_summary
                
                # Store GitLab logs if orchestrator fetched them
                if orchestration_result.job_logs:
                    combined_logs = "\n".join([
                        f"=== JOB: {job_log.job_name} (ID: {job_log.job_id}) ==="
                        f"\nStage: {job_log.stage}"
                        f"\nStatus: {job_log.status}"
                        f"\nFailure: {job_log.failure_reason or 'N/A'}"
                        f"\nDuration: {job_log.duration or 0}s"
                        f"\n\n{job_log.log_content}"
                        f"\n=== END JOB: {job_log.job_name} ===\n"
                        for job_log in orchestration_result.job_logs
                    ])
                    processed_email.gitlab_error_log = combined_logs
                
                processed_email.status = "completed"
                logger.info(
                    "Orchestrator processed email successfully",
                    project=gitlab_headers["project_name"] or gitlab_headers["project_id"],
                    pipeline=gitlab_headers["pipeline_id"],
                    orchestration_status=orchestration_result.status.value,
                    has_ai_analysis=bool(orchestration_result.error_analysis),
                    processing_time_ms=orchestration_result.total_processing_time_ms
                )
                
            except Exception as orchestration_error:
                processed_email.status = "orchestration_failed"
                processed_email.error_message = f"Orchestration failed: {str(orchestration_error)}\n\nOriginal email:\n{processed_email.error_message}"
                logger.error(
                    "Orchestration failed for email",
                    project_id=gitlab_headers["project_id"],
                    pipeline_id=gitlab_headers["pipeline_id"],
                    error=str(orchestration_error)
                )
            
            await self.db.commit()
            
        except Exception as e:
            # Update status to error if something goes wrong
            try:
                if 'processed_email' in locals():
                    processed_email.status = "error"
                    error_content = str(e)
                    if hasattr(msg, 'html') and msg.html:
                        error_content += f"\n\n--- EMAIL HTML CONTENT ---\n{msg.html}"
                    elif hasattr(msg, 'text') and msg.text:
                        error_content += f"\n\n--- EMAIL TEXT CONTENT ---\n{msg.text}"
                    processed_email.error_message = error_content
                    await self.db.commit()
            except Exception as commit_error:
                logger.error(
                    "Failed to update email status to error",
                    commit_error=str(commit_error)
                )
            
            logger.error(
                "Orchestrator failed to process email",
                message_id=getattr(msg, 'message_id', 'unknown'),
                subject=getattr(msg, 'subject', 'unknown'),
                error=str(e),
                exc_info=True
            )

    async def _is_email_already_processed(self, msg) -> bool:
        """Check if email message has already been processed."""
        try:
            # First check by message_id (more reliable)
            message_id_raw = msg.headers.get("message-id")
            if isinstance(message_id_raw, tuple) and message_id_raw:
                message_id = message_id_raw[0]
            else:
                message_id = message_id_raw
                
            if message_id:
                result = await self.db.execute(
                    select(ProcessedEmail).where(ProcessedEmail.message_id == message_id)
                )
                if result.scalar_one_or_none():
                    return True
            
            # Fallback: check by UID
            result = await self.db.execute(
                select(ProcessedEmail).where(ProcessedEmail.message_uid == msg.uid)
            )
            return result.scalar_one_or_none() is not None
            
        except Exception as e:
            logger.warning(
                "Error checking if email processed",
                message_uid=getattr(msg, 'uid', 'unknown'),
                error=str(e)
            )
            return False

    async def process_webhook(
        self,
        request: OrchestrationRequest,
        request_id: Optional[str] = None,
    ) -> OrchestrationResponse:
        """Process webhook and orchestrate error analysis.
        
        Args:
            request: Orchestration request
            request_id: Optional request ID
            
        Returns:
            Orchestration response
            
        Raises:
            OrchestrationError: When orchestration fails
        """
        if not request_id:
            request_id = str(uuid.uuid4())
        
        start_time = datetime.utcnow()
        
        # Create initial response
        response = OrchestrationResponse(
            request_id=request_id,
            status=OrchestrationStatus.PENDING,
            created_at=start_time,
            updated_at=start_time,
            project_id=request.webhook_data.project.id,
            pipeline_id=request.webhook_data.object_attributes.id,
            processing_steps=[],
        )
        
        self._active_analyses[request_id] = response
        
        try:
            logger.info(
                "Starting orchestration process",
                request_id=request_id,
                project_id=response.project_id,
                pipeline_id=response.pipeline_id,
            )
            
            # Update status
            response.status = OrchestrationStatus.PROCESSING
            response.updated_at = datetime.utcnow()
            response.processing_steps.append("Started orchestration process")
            
            # Step 1: Analyze webhook to determine failure type
            await self._analyze_webhook_event(request, response)
            
            # Step 2: Fetch additional data from GitLab
            await self._fetch_gitlab_data(request, response)
            
            # Step 3: Perform AI analysis
            await self._perform_ai_analysis(request, response)
            
            # Step 4: Create comprehensive error analysis
            await self._create_error_analysis(request, response)
            
            # Mark as completed
            response.status = OrchestrationStatus.COMPLETED
            response.completed_at = datetime.utcnow()
            response.total_processing_time_ms = int(
                (response.completed_at - response.created_at).total_seconds() * 1000
            )
            response.processing_steps.append("Orchestration completed successfully")
            
            logger.info(
                "Orchestration completed successfully",
                request_id=request_id,
                processing_time_ms=response.total_processing_time_ms,
            )
            
            return response
            
        except asyncio.TimeoutError:
            logger.error("Orchestration timeout", request_id=request_id)
            response.status = OrchestrationStatus.TIMEOUT
            response.error_message = "Analysis timed out"
            response.updated_at = datetime.utcnow()
            return response
            
        except Exception as e:
            logger.error("Orchestration failed", request_id=request_id, error=str(e))
            response.status = OrchestrationStatus.FAILED
            response.error_message = str(e)
            response.updated_at = datetime.utcnow()
            # Keep response in active analyses for a while even after completion
            self._active_analyses[request_id] = response
            
            # Schedule cleanup for completed/failed analyses after some time
            if response.status in [OrchestrationStatus.COMPLETED, OrchestrationStatus.FAILED]:
                cleanup_delay = 300  # Keep for 5 minutes
                logger.debug(
                    "Scheduling analysis cleanup",
                    request_id=request_id,
                    delay_seconds=cleanup_delay
                )
                asyncio.create_task(self._delayed_cleanup(request_id, cleanup_delay))
            
            return response

    async def _delayed_cleanup(self, request_id: str, delay_seconds: int) -> None:
        """Remove analysis from active analyses after delay."""
        try:
            await asyncio.sleep(delay_seconds)
            self._active_analyses.pop(request_id, None)
            logger.debug("Cleaned up analysis", request_id=request_id)
        except Exception as e:
            logger.error("Failed to cleanup analysis", request_id=request_id, error=str(e))

    async def _analyze_webhook_event(
        self,
        request: OrchestrationRequest,
        response: OrchestrationResponse,
    ) -> None:
        """Analyze webhook event to understand the failure."""
        logger.info("Analyzing webhook event", request_id=response.request_id)
        
        response.processing_steps.append("Analyzing webhook event")
        
        webhook_data = request.webhook_data
        
        # Determine failed jobs from webhook
        failed_job_ids = []
        
        if webhook_data.object_kind == "Pipeline Hook":
            # For pipeline webhooks, we need to fetch failed jobs
            if hasattr(webhook_data, 'builds') and webhook_data.builds:
                failed_job_ids = [
                    build.id for build in webhook_data.builds 
                    if build.status in ["failed", "canceled"]
                ]
        elif webhook_data.object_kind == "Job Hook":
            # For job webhooks, the failed job is in object_attributes
            if webhook_data.object_attributes.status in ["failed", "canceled"]:
                failed_job_ids = [webhook_data.object_attributes.id]
        
        response.failed_job_ids = failed_job_ids
        response.processing_steps.append(f"Identified {len(failed_job_ids)} failed jobs")
        
        logger.info(
            "Webhook analysis completed",
            request_id=response.request_id,
            failed_jobs=len(failed_job_ids),
        )

    async def _fetch_gitlab_data(
        self,
        request: OrchestrationRequest,
        response: OrchestrationResponse,
    ) -> None:
        """Fetch additional data from GitLab API."""
        logger.info("Fetching GitLab data", request_id=response.request_id)
        
        response.processing_steps.append("Fetching GitLab data")
        
        async with GitLabClient(
            base_url=settings.gitlab_base_url,
            api_token=settings.gitlab_api_token,
            timeout=settings.gitlab_api_timeout,
        ) as gitlab_client:
            
            try:
                # Fetch project information
                project_info = await gitlab_client.get_project_info(
                    response.project_id,
                    include_pipeline=True,
                )
                response.project_info = project_info
                response.processing_steps.append("Fetched project information")
                
                # Strategy 1: Use webhook data if available and complete
                webhook_has_logs = self._webhook_has_sufficient_logs(request.webhook_data)
                
                if not webhook_has_logs and settings.gitlab_auto_fetch_logs:
                    logger.info(
                        "Webhook lacks sufficient log data, fetching from GitLab API",
                        request_id=response.request_id
                    )
                    await self._fetch_logs_from_gitlab(gitlab_client, response)
                elif webhook_has_logs:
                    logger.info(
                        "Using log data from webhook",
                        request_id=response.request_id
                    )
                    self._extract_logs_from_webhook(request.webhook_data, response)
                else:
                    logger.warning(
                        "No log fetching strategy available",
                        request_id=response.request_id
                    )
                
                # Fetch additional context if configured
                await self._fetch_additional_context(gitlab_client, response, request)
                
            except GitLabAPIError as e:
                logger.error(
                    "GitLab API error during data fetch",
                    request_id=response.request_id,
                    error=str(e),
                )
                raise
        
        logger.info(
            "GitLab data fetch completed",
            request_id=response.request_id,
            job_logs=len(response.job_logs),
        )

    def _webhook_has_sufficient_logs(self, webhook_data) -> bool:
        """Check if webhook contains sufficient log data for analysis."""
        # Check if webhook includes job logs or detailed error information
        if hasattr(webhook_data, 'builds') and webhook_data.builds:
            for build in webhook_data.builds:
                if (hasattr(build, 'failure_reason') and build.failure_reason and 
                    len(build.failure_reason) > 50):  # Minimum meaningful error length
                    return True
                if hasattr(build, 'log') and build.log and len(build.log) > 100:
                    return True
        
        # Check job hook data
        if (webhook_data.object_kind == "Job Hook" and 
            hasattr(webhook_data.object_attributes, 'failure_reason')):
            failure_reason = webhook_data.object_attributes.failure_reason
            if failure_reason and len(failure_reason) > 50:
                return True
        
        return False

    def _extract_logs_from_webhook(self, webhook_data, response: OrchestrationResponse) -> None:
        """Extract log data from webhook payload."""
        job_logs = []
        
        if hasattr(webhook_data, 'builds') and webhook_data.builds:
            for build in webhook_data.builds:
                if build.status in ["failed", "canceled"]:
                    job_log = GitLabJobLog(
                        job_id=build.id,
                        job_name=build.name,
                        stage=build.stage,
                        status=build.status,
                        failure_reason=getattr(build, 'failure_reason', None),
                        log_content=getattr(build, 'log', '') or '',
                        started_at=getattr(build, 'started_at', None),
                        finished_at=getattr(build, 'finished_at', None),
                    )
                    job_logs.append(job_log)
        
        elif webhook_data.object_kind == "Job Hook":
            obj_attrs = webhook_data.object_attributes
            if obj_attrs.status in ["failed", "canceled"]:
                job_log = GitLabJobLog(
                    job_id=obj_attrs.id,
                    job_name=obj_attrs.name,
                    stage=obj_attrs.stage,
                    status=obj_attrs.status,
                    failure_reason=getattr(obj_attrs, 'failure_reason', None),
                    log_content='',  # Job hooks typically don't include logs
                    started_at=getattr(obj_attrs, 'started_at', None),
                    finished_at=getattr(obj_attrs, 'finished_at', None),
                )
                job_logs.append(job_log)
        
        response.job_logs = job_logs
        response.processing_steps.append(f"Extracted {len(job_logs)} job logs from webhook")

    async def _fetch_logs_from_gitlab(
        self, 
        gitlab_client: GitLabClient, 
        response: OrchestrationResponse
    ) -> None:
        """Fetch comprehensive logs from GitLab API."""
        
        if settings.gitlab_fetch_full_pipeline:
            # Fetch all jobs in pipeline for full context
            try:
                all_jobs = await gitlab_client.get_pipeline_jobs(
                    response.project_id,
                    response.pipeline_id
                )
                response.processing_steps.append(f"Fetched {len(all_jobs)} jobs from pipeline")
                
                # Focus on failed jobs but include some successful ones for context
                failed_jobs = [job for job in all_jobs if job.status in ["failed", "canceled"]]
                context_jobs = [job for job in all_jobs if job.status == "success"][:3]
                
                jobs_to_analyze = failed_jobs + context_jobs
                
            except Exception as e:
                logger.warning(
                    "Failed to fetch full pipeline jobs, falling back to failed jobs only",
                    request_id=response.request_id,
                    error=str(e)
                )
                jobs_to_analyze = response.failed_job_ids
        else:
            jobs_to_analyze = response.failed_job_ids
        
        # Fetch logs for selected jobs
        job_logs = []
        for job_id in jobs_to_analyze:
            try:
                job_log = await gitlab_client.get_job_log(
                    response.project_id,
                    job_id,
                    max_size_mb=settings.gitlab_max_log_size_mb,
                    context_lines=settings.gitlab_log_context_lines
                )
                job_logs.append(job_log)
                
                logger.debug(
                    "Fetched job log",
                    request_id=response.request_id,
                    job_id=job_id,
                    log_size=len(job_log.log_content),
                )
            except GitLabAPIError as e:
                logger.warning(
                    "Failed to fetch job log",
                    request_id=response.request_id,
                    job_id=job_id,
                    error=str(e),
                )
                response.warnings.append(f"Failed to fetch log for job {job_id}: {e}")
        
        response.job_logs = job_logs
        response.processing_steps.append(f"Fetched {len(job_logs)} job logs from GitLab API")

    async def _fetch_additional_context(
        self,
        gitlab_client: GitLabClient,
        response: OrchestrationResponse,
        request: OrchestrationRequest
    ) -> None:
        """Fetch additional context data based on configuration."""
        
        # Fetch CI configuration if requested
        if request.include_context:
            try:
                ci_config = await gitlab_client.get_ci_config(response.project_id)
                if ci_config and response.project_info:
                    response.project_info.ci_config = ci_config
                response.processing_steps.append("Fetched CI configuration")
            except Exception as e:
                logger.warning(
                    "Failed to fetch CI config",
                    request_id=response.request_id,
                    error=str(e),
                )
        
        # Fetch test reports if configured
        if settings.gitlab_fetch_test_reports:
            try:
                test_reports = await gitlab_client.get_pipeline_test_report(
                    response.project_id,
                    response.pipeline_id
                )
                if test_reports:
                    response.test_reports = test_reports
                    response.processing_steps.append("Fetched test reports")
            except Exception as e:
                logger.debug(
                    "No test reports available or failed to fetch",
                    request_id=response.request_id,
                    error=str(e),
                )
        
        # Fetch artifacts if configured (be careful with size)
        if settings.gitlab_fetch_artifacts:
            try:
                artifacts = await gitlab_client.get_job_artifacts_info(
                    response.project_id,
                    response.failed_job_ids
                )
                if artifacts:
                    response.artifacts_info = artifacts
                    response.processing_steps.append("Fetched artifacts information")
            except Exception as e:
                logger.debug(
                    "No artifacts available or failed to fetch",
                    request_id=response.request_id,
                    error=str(e),
                )
        
        # Fetch repository files if requested
        if request.include_repository_files:
            try:
                repo_files = await gitlab_client.get_project_files(
                    response.project_id,
                    recursive=False,
                )
                if response.project_info:
                    response.project_info.repository_files = repo_files[:50]  # Limit to 50 files
                response.processing_steps.append("Fetched repository file list")
            except Exception as e:
                logger.warning(
                    "Failed to fetch repository files",
                    request_id=response.request_id,
                    error=str(e),
                )

    async def _perform_ai_analysis(
        self,
        request: OrchestrationRequest,
        response: OrchestrationResponse,
    ) -> None:
        """Perform AI analysis on the gathered data."""
        logger.info("Starting AI analysis", request_id=response.request_id)
        
        response.status = OrchestrationStatus.ANALYZING
        response.processing_steps.append("Starting AI analysis")
        
        if not response.job_logs:
            logger.warning("No job logs available for analysis", request_id=response.request_id)
            response.warnings.append("No job logs available for AI analysis")
            return
        
        try:
            # Use the first failed job for analysis (could be enhanced to analyze all)
            primary_job_log = response.job_logs[0]
            
            # Prepare context data
            project_context = None
            if response.project_info:
                project_context = {
                    "project_name": response.project_info.project.name,
                    "project_description": response.project_info.project.description,
                    "default_branch": response.project_info.project.default_branch,
                    "namespace": response.project_info.project.namespace,
                }
            
            # Create AI analysis request
            ai_request = AIAnalysisRequest(
                analysis_type=AIAnalysisType.ERROR_DIAGNOSIS,
                job_log=primary_job_log.log_content,
                job_name=primary_job_log.job_name,
                stage=primary_job_log.stage,
                failure_reason=primary_job_log.failure_reason,
                project_context=project_context,
                ci_config=response.project_info.ci_config if response.project_info else None,
                repository_files=response.project_info.repository_files if response.project_info else None,
                custom_prompt=request.custom_analysis_prompt,
                provider=AIProvider(settings.default_ai_provider),
                temperature=settings.ai_temperature,
                max_tokens=settings.ai_max_tokens,
            )
            
            # Perform AI analysis with fallback providers
            fallback_providers = [
                provider for provider in self.ai_service.get_available_providers()
                if provider.value != settings.default_ai_provider
            ]
            
            ai_response = await asyncio.wait_for(
                self.ai_service.analyze_error(ai_request, fallback_providers),
                timeout=settings.ai_analysis_timeout,
            )
            
            response.ai_analysis = ai_response
            response.processing_steps.append(f"AI analysis completed using {ai_response.provider}")
            
            logger.info(
                "AI analysis completed",
                request_id=response.request_id,
                provider=ai_response.provider,
                confidence_score=ai_response.confidence_score,
                processing_time_ms=ai_response.processing_time_ms,
            )
            
        except asyncio.TimeoutError:
            logger.error("AI analysis timeout", request_id=response.request_id)
            response.warnings.append("AI analysis timed out")
        except AIServiceError as e:
            logger.error("AI service error", request_id=response.request_id, error=str(e))
            response.warnings.append(f"AI analysis failed: {e}")
        except Exception as e:
            logger.error("Unexpected error during AI analysis", request_id=response.request_id, error=str(e))
            response.warnings.append(f"AI analysis failed with unexpected error: {e}")

    async def _create_error_analysis(
        self,
        request: OrchestrationRequest,
        response: OrchestrationResponse,
    ) -> None:
        """Create comprehensive error analysis from gathered data."""
        logger.info("Creating error analysis", request_id=response.request_id)
        
        response.processing_steps.append("Creating comprehensive error analysis")
        
        # Determine error category and severity
        category = self._determine_error_category(response)
        severity = self._determine_error_severity(response)
        
        # Create error analysis
        error_analysis = ErrorAnalysis(
            category=category,
            severity=severity,
            title=self._generate_error_title(response),
            description=self._generate_error_description(response),
            root_cause=response.ai_analysis.root_cause if response.ai_analysis else None,
            affected_components=self._identify_affected_components(response),
            immediate_fixes=response.ai_analysis.immediate_actions if response.ai_analysis else [],
            long_term_solutions=response.ai_analysis.preventive_measures if response.ai_analysis else [],
            preventive_measures=self._generate_preventive_measures(response),
            related_documentation=self._generate_documentation_links(response),
            tags=self._generate_tags(response),
            confidence_score=response.ai_analysis.confidence_score if response.ai_analysis else 0.5,
            analysis_duration_ms=response.total_processing_time_ms,
            ai_provider_used=response.ai_analysis.provider if response.ai_analysis else "none",
        )
        
        response.error_analysis = error_analysis
        response.suggested_actions = error_analysis.immediate_fixes + error_analysis.long_term_solutions
        
        logger.info(
            "Error analysis created",
            request_id=response.request_id,
            category=category,
            severity=severity,
            confidence_score=error_analysis.confidence_score,
        )

    def _determine_error_category(self, response: OrchestrationResponse) -> ErrorCategory:
        """Determine error category from analysis data."""
        if response.ai_analysis and response.ai_analysis.results:
            # Use AI categorization if available
            for result in response.ai_analysis.results:
                if "build" in result.category.lower():
                    return ErrorCategory.BUILD_FAILURE
                elif "test" in result.category.lower():
                    return ErrorCategory.TEST_FAILURE
                elif "deploy" in result.category.lower():
                    return ErrorCategory.DEPLOYMENT_FAILURE
                elif "dependency" in result.category.lower():
                    return ErrorCategory.DEPENDENCY_ISSUE
                elif "config" in result.category.lower():
                    return ErrorCategory.CONFIGURATION_ERROR
        
        # Fallback to job stage analysis
        if response.job_logs:
            stage = response.job_logs[0].stage.lower()
            if stage in ["build", "compile"]:
                return ErrorCategory.BUILD_FAILURE
            elif stage in ["test", "unit_test", "integration_test"]:
                return ErrorCategory.TEST_FAILURE
            elif stage in ["deploy", "deployment", "release"]:
                return ErrorCategory.DEPLOYMENT_FAILURE
        
        return ErrorCategory.UNKNOWN

    def _determine_error_severity(self, response: OrchestrationResponse) -> ErrorSeverity:
        """Determine error severity from analysis data."""
        if response.ai_analysis:
            severity_map = {
                "critical": ErrorSeverity.CRITICAL,
                "high": ErrorSeverity.HIGH,
                "medium": ErrorSeverity.MEDIUM,
                "low": ErrorSeverity.LOW,
                "info": ErrorSeverity.INFO,
            }
            return severity_map.get(response.ai_analysis.severity_level, ErrorSeverity.MEDIUM)
        
        # Default to MEDIUM if no AI analysis
        return ErrorSeverity.MEDIUM

    def _generate_error_title(self, response: OrchestrationResponse) -> str:
        """Generate error title from analysis data."""
        if response.ai_analysis:
            return response.ai_analysis.summary
        
        if response.job_logs:
            job = response.job_logs[0]
            return f"{job.stage} job '{job.job_name}' failed"
        
        return "CI/CD Pipeline Failure"

    def _generate_error_description(self, response: OrchestrationResponse) -> str:
        """Generate error description from analysis data."""
        if response.ai_analysis:
            return response.ai_analysis.summary
        
        parts = []
        if response.job_logs:
            job = response.job_logs[0]
            parts.append(f"Job '{job.job_name}' in stage '{job.stage}' failed.")
            if job.failure_reason:
                parts.append(f"Failure reason: {job.failure_reason}")
        
        return " ".join(parts) if parts else "CI/CD pipeline encountered an error."

    def _identify_affected_components(self, response: OrchestrationResponse) -> List[str]:
        """Identify affected components from analysis data."""
        components = []
        
        if response.job_logs:
            for job in response.job_logs:
                components.append(f"{job.stage}:{job.job_name}")
        
        if response.project_info:
            components.append(f"project:{response.project_info.project.name}")
        
        return components

    def _generate_preventive_measures(self, response: OrchestrationResponse) -> List[str]:
        """Generate preventive measures."""
        measures = []
        
        if response.ai_analysis:
            measures.extend(response.ai_analysis.preventive_measures)
        
        # Add generic preventive measures
        measures.extend([
            "Implement pre-commit hooks for code quality checks",
            "Add comprehensive unit and integration tests",
            "Set up staging environment for testing",
            "Monitor build performance and dependencies",
        ])
        
        return list(set(measures))  # Remove duplicates

    def _generate_documentation_links(self, response: OrchestrationResponse) -> List[str]:
        """Generate relevant documentation links."""
        links = []
        
        if response.ai_analysis and response.ai_analysis.results:
            for result in response.ai_analysis.results:
                if result.documentation_links:
                    links.extend(result.documentation_links)
        
        return links

    def _generate_tags(self, response: OrchestrationResponse) -> List[str]:
        """Generate tags for the error analysis."""
        tags = []
        
        if response.ai_analysis:
            tags.extend(response.ai_analysis.tags)
        
        if response.job_logs:
            for job in response.job_logs:
                tags.extend([job.stage, job.status])
        
        if response.error_analysis:
            tags.extend([response.error_analysis.category, response.error_analysis.severity])
        
        return list(set(tags))  # Remove duplicates

    async def get_analysis_status(self, request_id: str) -> Optional[OrchestrationResponse]:
        """Get the status of an ongoing analysis.
        
        Args:
            request_id: Request ID to check
            
        Returns:
            Orchestration response if found, None otherwise
        """
        return self._active_analyses.get(request_id)

    async def list_active_analyses(self) -> List[OrchestrationResponse]:
        """List all active analyses.
        
        Returns:
            List of active orchestration responses
        """
        return list(self._active_analyses.values())

    async def health_check(self) -> Dict[str, bool]:
        """Perform health check on orchestration service dependencies.
        
        Returns:
            Health status of dependencies
        """
        health_status = {
            "orchestration_service": True,
            "ai_service": False,
            "gitlab_client": False,
        }
        
        try:
            # Check AI service
            ai_health = await self.ai_service.health_check()
            health_status["ai_service"] = any(ai_health.values())
            health_status.update({f"ai_{k}": v for k, v in ai_health.items()})
        except Exception as e:
            logger.warning("AI service health check failed", error=str(e))
        
        try:
            # Check GitLab client
            async with GitLabClient() as gitlab_client:
                health_status["gitlab_client"] = await gitlab_client.health_check()
        except Exception as e:
            logger.warning("GitLab client health check failed", error=str(e))
        
        return health_status
