"""Orchestration service for managing CI/CD error analysis workflow."""

import asyncio
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import structlog
from sqlalchemy.future import select
from imap_tools import AND

from ..core.config import settings
from ..core.exceptions import (
    OrchestrationError,
    AnalysisTimeoutError,
    GitLabAPIError,
    AIServiceError,
)
from ..core.database import get_database_session
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
from .gitlab import GitLabClient
from .ai_service import AIService

logger = structlog.get_logger(__name__)


class OrchestrationService:
    """Main orchestration service for CI/CD error analysis."""

    def __init__(self):
        self.ai_service = AIService()
        self._active_analyses: Dict[str, OrchestrationResponse] = {}
        # Email monitoring state
        self._email_monitoring_task: Optional[asyncio.Task] = None
        self._email_monitoring_running = False
        self._last_email_check: Optional[datetime] = None

    @staticmethod
    def _clean_error_message(message: str) -> str:
        """Clean error message by trimming whitespace and normalizing line endings."""
        if not message:
            return ""
        return message.strip().replace('\r\n', '\n').replace('\r', '\n')

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
            from .email import EmailUtils
            
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
        from .email import EmailUtils
        
        try:
            # Check if we've already processed this message
            if await self._is_email_already_processed(msg):
                logger.debug(
                    "Email already processed",
                    message_id=getattr(msg, 'message_id', msg.uid)
                )
                return

            # Use database session for this operation
            async with get_database_session() as db:
                # Create database record
                processed_email = EmailUtils.create_processed_email_record(msg)
                db.add(processed_email)
                await db.commit()

                # Extract GitLab headers
                gitlab_headers, error_msg = EmailUtils.extract_gitlab_headers(msg)
                
                if not gitlab_headers:
                    processed_email.status = "no_gitlab_headers"
                    processed_email.error_message = self._clean_error_message(error_msg)
                    await db.commit()
                    
                    logger.warning(
                        "No GitLab headers found in email",
                        subject=msg.subject,
                        from_email=msg.from_,
                        error=error_msg
                    )
                    return

                # Update processed email with GitLab data
                processed_email.project_id = gitlab_headers.get("project_id")
                processed_email.project_name = gitlab_headers.get("project_name")
                processed_email.project_path = gitlab_headers.get("project_path")
                processed_email.pipeline_id = gitlab_headers.get("pipeline_id")
                processed_email.pipeline_ref = gitlab_headers.get("pipeline_ref")
                processed_email.pipeline_status = gitlab_headers.get("pipeline_status")
                
                # Store email content
                if hasattr(msg, 'html') and msg.html:
                    processed_email.error_message = self._clean_error_message(msg.html)
                elif hasattr(msg, 'text') and msg.text:
                    processed_email.error_message = self._clean_error_message(msg.text)
                
                processed_email.status = "processing_pipeline"
                await db.commit()

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

Immediate Fixes:
{chr(10).join([f"- {fix}" for fix in analysis.immediate_fixes])}

Long-term Solutions:
{chr(10).join([f"- {solution}" for solution in analysis.long_term_solutions])}

Processing Details:
- Request ID: {orchestration_result.request_id}
- Processing Time: {orchestration_result.total_processing_time_ms}ms
- Status: {orchestration_result.status.value}

=== ORIGINAL EMAIL CONTENT ===
{processed_email.error_message or 'No email content'}
"""
                        processed_email.error_message = self._clean_error_message(analysis_summary)

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

                    # Chỉ lưu completed nếu orchestration_result.status là COMPLETED
                    if getattr(orchestration_result, "status", None) and orchestration_result.status.name == "COMPLETED":
                        processed_email.status = "completed"
                        logger.info(
                            "Orchestrator processed email successfully",
                            project=gitlab_headers["project_name"] or gitlab_headers["project_id"],
                            pipeline=gitlab_headers["pipeline_id"],
                            orchestration_status=orchestration_result.status.value,
                        )
                    else:
                        processed_email.status = orchestration_result.status.value if getattr(orchestration_result, "status", None) else "error"
                        logger.error(
                            "Orchestrator did NOT complete successfully. See orchestration_result for details.",
                            project=gitlab_headers["project_name"] or gitlab_headers["project_id"],
                            pipeline=gitlab_headers["pipeline_id"],
                            orchestration_status=getattr(orchestration_result, "status", None),
                            orchestration_error=getattr(orchestration_result, "error_message", None),
                        )
                    
                except Exception as orchestration_error:
                    logger.error(
                        "Orchestrator pipeline failed",
                        message_id=getattr(msg, 'message_id', msg.uid),
                        error=str(orchestration_error),
                        exc_info=True
                    )
                    processed_email.status = "orchestration_failed"
                    processed_email.error_message = f"Orchestration failed: {str(orchestration_error)}"
                
                finally:
                    # Always update the final status
                    await db.commit()
        
        except Exception as e:
            # Update status to error if something goes wrong
            try:
                async with get_database_session() as error_db:
                    if 'processed_email' in locals() and hasattr(processed_email, 'id'):
                        # Re-fetch the email from database to update it
                        result = await error_db.execute(
                            select(ProcessedEmail).where(ProcessedEmail.id == processed_email.id)
                        )
                        db_email = result.scalars().first()
                        if db_email:
                            db_email.status = "error"
                            error_content = str(e)
                            if hasattr(msg, 'html') and msg.html:
                                error_content += f"\n\n--- EMAIL HTML CONTENT ---\n{msg.html}"
                            elif hasattr(msg, 'text') and msg.text:
                                error_content += f"\n\n--- EMAIL TEXT CONTENT ---\n{msg.text}"
                            db_email.error_message = self._clean_error_message(error_content)
                            await error_db.commit()
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
        """Check if email message has already been processed successfully."""
        try:
            async with get_database_session() as db:
                # First check by message_id (more reliable)
                headers_lower = {k.lower(): v for k, v in msg.headers.items()}
                message_id_raw = headers_lower.get("message-id")
                if isinstance(message_id_raw, tuple) and message_id_raw:
                    message_id = message_id_raw[0]
                else:
                    message_id = message_id_raw
                    
                if message_id:
                    result = await db.execute(
                        select(ProcessedEmail).where(ProcessedEmail.message_id == message_id)
                    )
                    email_record = result.scalar_one_or_none()
                    if email_record:
                        # Only skip if email was successfully completed
                        # Allow reprocessing for failed, error, or incomplete statuses
                        if email_record.status == "completed":
                            return True
                        else:
                            logger.info(
                                "Email found but not completed, will reprocess",
                                message_id=message_id,
                                current_status=email_record.status,
                                subject=msg.subject
                            )
                            # Delete the incomplete record to allow fresh processing
                            await db.delete(email_record)
                            await db.commit()
                            return False
                
                # Fallback: check by UID
                result = await db.execute(
                    select(ProcessedEmail).where(ProcessedEmail.message_uid == msg.uid)
                )
                email_record = result.scalar_one_or_none()
                if email_record:
                    # Only skip if email was successfully completed
                    if email_record.status == "completed":
                        return True
                    else:
                        logger.info(
                            "Email found by UID but not completed, will reprocess",
                            message_uid=msg.uid,
                            current_status=email_record.status,
                            subject=msg.subject
                        )
                        # Delete the incomplete record to allow fresh processing
                        await db.delete(email_record)
                        await db.commit()
                        return False
                
                return False
                
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
                "Starting process webhook or email",
                request_id=request_id,
                project_id=response.project_id,
                pipeline_id=response.pipeline_id,
            )
            
            # Update status
            response.status = OrchestrationStatus.PROCESSING
            response.updated_at = datetime.utcnow()
            response.processing_steps.append(
                "Started process webhook or email")
            
            # Step 1: Analyze webhook to determine failure type
            await self._analyze_webhook_event(request, response)
            
            # Step 2: Fetch additional data from GitLab
            await self._fetch_gitlab_data(request, response)
            
            # Step 3: Fetch detailed logs from GitLab
            await self._fetch_detailed_gitlab_logs(response)
            
            # Step 4: Perform AI analysis
            await self._perform_ai_analysis(request, response)
            
            # Step 5: Create comprehensive error analysis
            await self._create_error_analysis(request, response)
            
            # Validation: Only mark as completed if we have actual job logs
            if not response.job_logs:
                logger.warning(
                    "Process completed but no job logs were fetched - marking as failed",
                    request_id=request_id,
                    project_id=response.project_id,
                    pipeline_id=response.pipeline_id
                )
                response.status = OrchestrationStatus.FAILED
                response.error_message = "No job logs were successfully fetched from GitLab"
                response.processing_steps.append("Process failed: No job logs fetched")
                return response
            
            # Mark as completed only if we have logs
            response.status = OrchestrationStatus.COMPLETED
            response.completed_at = datetime.utcnow()
            response.total_processing_time_ms = int(
                (response.completed_at - response.created_at).total_seconds() * 1000
            )
            response.processing_steps.append("Process webhook or email completed successfully")
            
            logger.info(
                "Process webhook or email completed successfully",
                request_id=request_id,
                processing_time_ms=response.total_processing_time_ms,
                job_logs_fetched=len(response.job_logs),
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
        """Analyze webhook event to identify failed jobs."""
        logger.info("Analyzing webhook event to identify failed jobs", request_id=response.request_id)
        
        response.processing_steps.append("Analyzing webhook event")
        
        webhook_data = request.webhook_data
        failed_job_ids = []
        failed_job_details = []
        
        logger.info(
            "Webhook analysis details",
            request_id=response.request_id,
            webhook_type=webhook_data.object_kind,
            has_builds=hasattr(webhook_data, 'builds') and webhook_data.builds is not None,
            builds_count=len(webhook_data.builds) if hasattr(webhook_data, 'builds') and webhook_data.builds else 0,
        )
        
        if webhook_data.object_kind == "Pipeline Hook":
            # For pipeline webhooks, extract failed jobs from builds
            if hasattr(webhook_data, 'builds') and webhook_data.builds:
                for build in webhook_data.builds:
                    if build.status in ["failed", "canceled"]:
                        failed_job_ids.append(build.id)
                        failed_job_details.append({
                            "job_id": build.id,
                            "job_name": build.name,
                            "job_stage": build.stage,
                            "job_status": build.status,
                            "failure_reason": getattr(build, 'failure_reason', None)
                        })
                        
                logger.info(
                    "Extracted failed jobs from pipeline webhook",
                    request_id=response.request_id,
                    failed_job_count=len(failed_job_ids),
                    failed_jobs=[f"{detail['job_name']}({detail['job_stage']}):{detail['job_status']}" for detail in failed_job_details],
                )
                        
        elif webhook_data.object_kind == "Job Hook":
            # For job webhooks, the failed job is in object_attributes
            obj_attrs = webhook_data.object_attributes
            if obj_attrs.status in ["failed", "canceled"]:
                failed_job_ids.append(obj_attrs.id)
                failed_job_details.append({
                    "job_id": obj_attrs.id,
                    "job_name": getattr(obj_attrs, 'name', 'unknown'),
                    "job_stage": getattr(obj_attrs, 'stage', 'unknown'),
                    "job_status": obj_attrs.status,
                    "failure_reason": getattr(obj_attrs, 'failure_reason', None)
                })
                
                logger.info(
                    "Extracted failed job from job webhook",
                    request_id=response.request_id,
                    job_id=obj_attrs.id,
                    job_name=getattr(obj_attrs, 'name', 'unknown'),
                    job_stage=getattr(obj_attrs, 'stage', 'unknown'),
                    job_status=obj_attrs.status,
                )
        
        else:
            logger.warning(
                "Unknown webhook type for failed job extraction",
                request_id=response.request_id,
                webhook_type=webhook_data.object_kind,
            )
        
        response.failed_job_ids = failed_job_ids
        # Note: Store detailed info in processing_steps instead of non-existent field
        
        if failed_job_ids:
            response.processing_steps.append(f"Identified {len(failed_job_ids)} failed jobs from webhook: {', '.join([detail['job_name'] for detail in failed_job_details])}")
        else:
            response.processing_steps.append("No failed jobs identified from webhook - will query GitLab API directly")
        
        logger.info(
            "Webhook analysis completed",
            request_id=response.request_id,
            failed_jobs_count=len(failed_job_ids),
            extraction_method="webhook_data_analysis",
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
                await self._fetch_gitlab_context(gitlab_client, response, request)
                
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

    async def _fetch_detailed_gitlab_logs(
        self,
        response: OrchestrationResponse,
    ) -> None:
        """Fetch detailed logs and context from GitLab instance.
        
        This method connects to the configured GitLab instance
        to fetch comprehensive error logs and context for AI analysis.
        """
        logger.info(
            "Fetching detailed logs from GitLab",
            request_id=response.request_id,
            project_id=response.project_id,
            pipeline_id=response.pipeline_id,
            gitlab_url=settings.gitlab_base_url,
        )
        
        response.processing_steps.append("Fetching detailed logs from GitLab")
        
        async with GitLabClient(
            base_url=settings.gitlab_base_url,
            api_token=settings.gitlab_api_token,
            timeout=settings.gitlab_api_timeout,
        ) as gitlab_client:
            
            try:
                # Get fresh pipeline information from GitLab
                pipeline = await gitlab_client.get_pipeline(
                    response.project_id, 
                    response.pipeline_id
                )
                
                logger.info(
                    "Pipeline info from GitLab",
                    request_id=response.request_id,
                    pipeline_status=pipeline.status,
                    pipeline_ref=pipeline.ref,
                )
                
                # Get only failed jobs - no need to fetch all jobs since we only analyze failures
                failed_jobs = await gitlab_client.get_failed_jobs(
                    response.project_id, 
                    response.pipeline_id
                )
                
                logger.info(
                    "Failed job analysis from GitLab",
                    request_id=response.request_id,
                    failed_jobs=len(failed_jobs),
                    failed_job_names=[job.name for job in failed_jobs] if failed_jobs else [],
                    pipeline_status=pipeline.status.value if hasattr(pipeline.status, 'value') else str(pipeline.status),
                )
                
                # If no failed jobs found but email reported failure, 
                # check for retried/historical failures in the pipeline
                if len(failed_jobs) == 0 and pipeline.status.value == "success":
                    logger.warning(
                        "Pipeline is now successful but email reported failure - checking for retried/historical failures",
                        request_id=response.request_id,
                        pipeline_status=pipeline.status.value,
                    )
                    
                    # Get all jobs including retried ones to find original failures
                    try:
                        all_jobs_with_retries = await gitlab_client.get_pipeline_jobs(
                            response.project_id, 
                            response.pipeline_id,
                            include_retried=True  # Include retried jobs
                        )
                        
                        # Look for jobs that failed before being retried
                        historical_failed_jobs = [
                            job for job in all_jobs_with_retries 
                            if job.status in ["failed", "canceled"] or 
                            (hasattr(job, 'failure_reason') and job.failure_reason)
                        ]
                        
                        logger.info(
                            "Found historical failed jobs from retries",
                            request_id=response.request_id,
                            total_with_retries=len(all_jobs_with_retries),
                            historical_failures=len(historical_failed_jobs),
                        )
                        
                        if historical_failed_jobs:
                            failed_jobs = historical_failed_jobs[:3]  # Limit to first 3 failures
                            
                    except Exception as retry_error:
                        logger.warning(
                            "Failed to fetch retried jobs",
                            request_id=response.request_id,
                            error=str(retry_error),
                        )
                
                # Fetch detailed logs for failed jobs with enhanced context
                enhanced_job_logs = []
                
                for job in failed_jobs:
                    try:
                        # Get comprehensive job log with context
                        job_log = await gitlab_client.get_job_log(
                            response.project_id,
                            job.id,
                            max_size_mb=10,  # Increase limit for detailed analysis
                            context_lines=50  # More context around errors
                        )
                        enhanced_job_logs.append(job_log)
                        
                        logger.info(
                            "Fetched detailed job log from GitLab",
                            request_id=response.request_id,
                            job_id=job.id,
                            job_name=job.name,
                            job_stage=job.stage,
                            log_size=len(job_log.log_content) if job_log.log_content else 0,
                        )
                        
                    except Exception as e:
                        logger.warning(
                            "Failed to fetch job log from GitLab",
                            request_id=response.request_id,
                            job_id=job.id,
                            error=str(e),
                        )
                
                # Update response with enhanced logs from GitLab
                if enhanced_job_logs:
                    # Replace or merge with existing logs
                    response.job_logs = enhanced_job_logs
                    response.processing_steps.append(
                        f"Fetched {len(enhanced_job_logs)} detailed job logs from GitLab"
                    )
                
                # Fetch additional context from GitLab
                await self._fetch_additional_context(gitlab_client, response)
                
            except GitLabAPIError as e:
                logger.error(
                    "Failed to fetch data from GitLab",
                    request_id=response.request_id,
                    error=str(e),
                    status_code=getattr(e, 'status_code', None),
                )
                # Don't fail the entire process, continue with existing data
                response.processing_steps.append(
                    f"Warning: Failed to fetch from GitLab: {str(e)}"
                )
                
            except Exception as e:
                logger.error(
                    "Unexpected error fetching from GitLab",
                    request_id=response.request_id,
                    error=str(e),
                )
                response.processing_steps.append(
                    f"Warning: Unexpected error with GitLab: {str(e)}"
                )
                # If this is a critical validation error, we should re-raise to fail the process
                if "validation errors" in str(e).lower():
                    logger.error(
                        "Critical validation error in GitLab response - failing process",
                        request_id=response.request_id,
                        error=str(e)
                    )
                    raise
        
        logger.info(
            "GitLab fetch completed",
            request_id=response.request_id,
            final_job_logs=len(response.job_logs),
        )

    async def _fetch_additional_context(
        self,
        gitlab_client: GitLabClient,
        response: OrchestrationResponse,
    ) -> None:
        """Fetch additional context data from GitLab for comprehensive analysis."""
        
        try:
            # Get CI configuration for pipeline context
            ci_config = await gitlab_client.get_ci_config(
                response.project_id,
                ref="main"  # or get from pipeline ref
            )
            
            if ci_config:
                response.ci_config = ci_config
                response.processing_steps.append("Fetched CI configuration from GitLab")
            
            # Get project files that might be relevant to the error
            try:
                project_files = await gitlab_client.get_project_files(
                    response.project_id,
                    path="",  # Root directory
                    ref="main"
                )
                
                # Store relevant files (configuration, requirements, etc.)
                relevant_files = [
                    f for f in project_files[:20]  # Limit to first 20 files
                    if any(pattern in f.get('name', '').lower() for pattern in [
                        'requirements', 'package.json', 'pom.xml', 'build.gradle',
                        'dockerfile', 'docker-compose', '.gitlab-ci', 'makefile'
                    ])
                ]
                
                if relevant_files:
                    response.project_files = relevant_files
                    response.processing_steps.append(
                        f"Identified {len(relevant_files)} relevant project files"
                    )
                    
            except Exception as e:
                logger.warning(
                    "Failed to fetch project files from GitLab",
                    request_id=response.request_id,
                    error=str(e),
                )
            
            # Get test reports if available
            try:
                test_reports = await gitlab_client.get_pipeline_test_report(
                    response.project_id,
                    response.pipeline_id
                )
                
                if test_reports:
                    response.test_reports = test_reports
                    response.processing_steps.append("Fetched test reports from GitLab")
                    
            except Exception as e:
                logger.debug(
                    "No test reports available from GitLab",
                    request_id=response.request_id,
                    error=str(e),
                )
            
            # Get artifacts information for failed jobs
            if response.failed_job_ids:
                try:
                    artifacts_info = await gitlab_client.get_job_artifacts_info(
                        response.project_id,
                        response.failed_job_ids
                    )
                    
                    if artifacts_info:
                        response.artifacts_info = artifacts_info
                        response.processing_steps.append("Fetched artifacts information")
                        
                except Exception as e:
                    logger.debug(
                        "Failed to fetch artifacts info from GitLab",
                        request_id=response.request_id,
                        error=str(e),
                    )
                    
        except Exception as e:
            logger.error(
                "Error fetching context",
                request_id=response.request_id,
                error=str(e),
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
        """Fetch failed job logs from GitLab API - identify and fetch only failed jobs."""
        
        # Strategy 1: Get failed jobs directly using GitLab API
        try:
            failed_jobs = await gitlab_client.get_failed_jobs(
                response.project_id,
                response.pipeline_id
            )
            
            logger.info(
                "Identified failed jobs from GitLab API",
                request_id=response.request_id,
                failed_jobs_count=len(failed_jobs),
                failed_job_names=[job.name for job in failed_jobs] if failed_jobs else [],
                failed_job_stages=[job.stage for job in failed_jobs] if failed_jobs else [],
            )
            
            response.processing_steps.append(f"Found {len(failed_jobs)} failed jobs: {', '.join([job.name for job in failed_jobs])}")
            
            # Fetch logs for each failed job 
            job_logs = []
            for job in failed_jobs:
                try:
                    logger.info(
                        "Fetching log for failed job",
                        request_id=response.request_id,
                        job_id=job.id,
                        job_name=job.name,
                        job_stage=job.stage,
                        job_status=job.status.value if hasattr(job.status, 'value') else str(job.status),
                        failure_reason=getattr(job, 'failure_reason', 'No failure reason provided'),
                    )
                    
                    job_log = await gitlab_client.get_job_log(
                        response.project_id,
                        job.id,
                        max_size_mb=5,  # Reasonable limit for logs
                        context_lines=20  # Some context around errors
                    )
                    job_logs.append(job_log)
                    
                    logger.info(
                        "Successfully fetched failed job log",
                        request_id=response.request_id,
                        job_id=job.id,
                        job_name=job.name,
                        job_stage=job.stage,
                        log_size=len(job_log.log_content) if job_log.log_content else 0,
                        has_failure_reason=bool(job_log.failure_reason),
                    )
                    
                except Exception as e:
                    logger.warning(
                        "Failed to fetch log for specific failed job",
                        request_id=response.request_id,
                        job_id=job.id,
                        job_name=getattr(job, 'name', 'unknown'),
                        error=str(e),
                    )
            
            response.job_logs = job_logs
            response.processing_steps.append(f"Successfully fetched logs for {len(job_logs)}/{len(failed_jobs)} failed jobs")
            
        except Exception as e:
            logger.warning(
                "Failed to get failed jobs directly, using fallback approach",
                request_id=response.request_id,
                error=str(e)
            )
            
            # Strategy 2: Fallback - get all jobs and filter failed ones manually
            await self._fetch_logs_fallback_method(gitlab_client, response)

    async def _fetch_logs_fallback_method(
        self,
        gitlab_client: GitLabClient, 
        response: OrchestrationResponse
    ) -> None:
        """Fallback method to identify failed jobs when direct failed jobs API fails."""
        
        logger.info(
            "Using fallback method to identify failed jobs - fetching all jobs to filter manually",
            request_id=response.request_id,
        )
        
        try:
            # Only fetch all jobs as fallback when direct failed jobs API fails
            all_jobs = await gitlab_client.get_pipeline_jobs(
                response.project_id,
                response.pipeline_id
            )
            
            # Manually filter failed jobs
            failed_jobs = [
                job for job in all_jobs 
                if job.status in ["failed", "canceled", "manual"] and 
                job.status != "success"
            ]
            
            logger.info(
                "Fallback job analysis - manually filtered failed jobs",
                request_id=response.request_id,
                total_jobs=len(all_jobs),
                failed_jobs=len(failed_jobs),
                all_job_statuses=[f"{job.name}:{job.status}" for job in all_jobs],
                failed_job_details=[f"{job.name}({job.stage}):{job.status}" for job in failed_jobs],
            )
            
            # If we still have failed_job_ids from webhook, use those as backup
            if not failed_jobs and response.failed_job_ids:
                logger.info(
                    "No failed jobs found in pipeline, using webhook failed_job_ids",
                    request_id=response.request_id,
                    webhook_failed_job_ids=response.failed_job_ids,
                )
                
                job_logs = []
                for job_id in response.failed_job_ids:
                    try:
                        job_log = await gitlab_client.get_job_log(
                            response.project_id,
                            job_id,
                            max_size_mb=5,
                            context_lines=20
                        )
                        job_logs.append(job_log)
                        
                        logger.info(
                            "Fetched log using webhook job ID",
                            request_id=response.request_id,
                            job_id=job_id,
                            log_size=len(job_log.log_content) if job_log.log_content else 0,
                        )
                        
                    except Exception as job_error:
                        logger.warning(
                            "Failed to fetch job log by webhook ID",
                            request_id=response.request_id,
                            job_id=job_id,
                            error=str(job_error),
                        )
                
                response.job_logs = job_logs
                response.processing_steps.append(f"Fetched {len(job_logs)} job logs using webhook job IDs")
                
            else:
                # Fetch logs for manually identified failed jobs
                job_logs = []
                for job in failed_jobs:
                    try:
                        job_log = await gitlab_client.get_job_log(
                            response.project_id,
                            job.id,
                            max_size_mb=5,
                            context_lines=20
                        )
                        job_logs.append(job_log)
                        
                        logger.info(
                            "Fetched log for manually identified failed job",
                            request_id=response.request_id,
                            job_id=job.id,
                            job_name=job.name,
                            job_stage=job.stage,
                            log_size=len(job_log.log_content) if job_log.log_content else 0,
                        )
                        
                    except Exception as job_error:
                        logger.warning(
                            "Failed to fetch log for manually identified job",
                            request_id=response.request_id,
                            job_id=job.id,
                            job_name=getattr(job, 'name', 'unknown'),
                            error=str(job_error),
                        )
                
                response.job_logs = job_logs
                response.processing_steps.append(f"Fetched {len(job_logs)} job logs using fallback manual identification")
                
        except Exception as fallback_error:
            logger.error(
                "Fallback method also failed",
                request_id=response.request_id,
                error=str(fallback_error),
            )
            response.processing_steps.append("Failed to identify failed jobs using all methods")

    async def _fetch_gitlab_context(
        self,
        gitlab_client: GitLabClient,
        response: OrchestrationResponse,
        request: OrchestrationRequest
    ) -> None:
        """Fetch only essential context data - simplified to just get failed job logs."""
        
        # Only fetch CI configuration if explicitly requested
        if request.include_context:
            try:
                ci_config = await gitlab_client.get_ci_config(response.project_id)
                if ci_config and response.project_info:
                    response.project_info.ci_config = ci_config
                response.processing_steps.append("Fetched CI configuration")
            except Exception as e:
                logger.debug(
                    "No CI config available",
                    request_id=response.request_id,
                    error=str(e),
                )
        
        # Skip test reports, artifacts, and repository files - not needed for basic error analysis
        logger.debug(
            "Skipping optional GitLab context (test reports, artifacts, repo files) - focusing on job logs only",
            request_id=response.request_id
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
