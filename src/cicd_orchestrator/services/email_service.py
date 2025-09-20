"""Email utilities for parsing GitLab pipeline notifications.

This module provides utilities for processing GitLab pipeline notification emails
and converting them into structured data that can be processed by the orchestration
service. The main class EmailUtils contains static methods for email parsing, 
header extraction, and data validation.

Example:
    Extract GitLab headers from an email message:
    
    >>> gitlab_headers, error = EmailUtils.extract_gitlab_headers(email_msg)
    >>> if gitlab_headers:
    ...     webhook = EmailUtils.create_webhook_from_email(email_msg, gitlab_headers)
    ...     processed_email = EmailUtils.create_processed_email_record(email_msg)

Classes:
    EmailUtils: Static utility methods for email processing
    EmailMonitoringService: Deprecated service class (raises DeprecationWarning)
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Tuple, Any, Union, List

import structlog
from imap_tools import MailBox

from ..core.config import settings
from ..models.email import ProcessedEmail
from ..models.gitlab import (
    GitLabWebhook, 
    GitLabEventType, 
    GitLabWebhookObjectAttributes, 
    GitLabProject, 
    GitLabUser
)

logger = structlog.get_logger(__name__)


class EmailUtils:
    """Utility class for email parsing and GitLab header extraction.
    
    This class provides static methods for email processing that can be used
    by the OrchestrationService. It does NOT handle orchestration logic itself.
    
    All methods are static and stateless, making this class a pure utility
    without any instance state or side effects.
    
    Attributes:
        None (all methods are static)
    """

    @staticmethod
    def extract_gitlab_headers(
        msg: Any
    ) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
        """Extract GitLab headers from email message.

        Parses GitLab-specific email headers to extract project and pipeline information.
        Handles both tuple and string header values, validates data types and formats.

        Args:
            msg: Email message object from imap_tools library
                Expected to have .headers attribute containing email headers

        Returns:
            Tuple containing:
                - gitlab_headers_dict: Dictionary with GitLab information if successful, 
                  None if extraction failed. Contains keys:
                  * project_id: GitLab project ID (required)
                  * project_name: Project name (optional)
                  * project_path: Project path/namespace (optional)
                  * pipeline_id: Pipeline ID (required)
                  * pipeline_ref: Git reference (branch/tag) (optional)
                  * pipeline_status: Pipeline status (optional)
                  * pipeline_url: Direct URL to pipeline (optional)
                  * project_url: Direct URL to project (optional)
                  * commit_sha: Git commit SHA (optional)
                - error_message: Error description if extraction failed, None if successful

        Raises:
            None: All exceptions are caught and returned as error messages

        Examples:
            >>> headers, error = EmailUtils.extract_gitlab_headers(email_msg)
            >>> if headers:
            ...     print(f"Project: {headers['project_id']}, Pipeline: {headers['pipeline_id']}")
            ... else:
            ...     print(f"Extraction failed: {error}")
        """
        """Extract GitLab headers from email message.

        Args:
            msg: Email message object from imap_tools

        Returns:
            Tuple of (gitlab_headers_dict, error_message)
            - gitlab_headers_dict: Dict with GitLab info if successful, None if failed
            - error_message: Error description if extraction failed, None if successful
        """
        try:
            headers = dict(msg.headers)

            # Safely extract values from headers (they might be tuples)
            project_id_raw = headers.get("x-gitlab-project-id")
            project_name_raw = headers.get("x-gitlab-project")
            project_path_raw = headers.get("x-gitlab-project-path")

            pipeline_id_raw = headers.get("x-gitlab-pipeline-id")
            pipeline_ref_raw = headers.get("x-gitlab-pipeline-ref")
            pipeline_status_raw = headers.get("x-gitlab-pipeline-status", "")

            # Additional GitLab headers for enhanced processing
            pipeline_url_raw = headers.get("x-gitlab-pipeline-url")
            project_url_raw = headers.get("x-gitlab-project-url")
            commit_sha_raw = headers.get("x-gitlab-commit-sha")

            # Convert tuple to string if needed
            project_id = EmailUtils._extract_header_value(project_id_raw)
            project_name = EmailUtils._extract_header_value(project_name_raw)
            project_path = EmailUtils._extract_header_value(project_path_raw)

            pipeline_id = EmailUtils._extract_header_value(pipeline_id_raw)
            pipeline_ref = EmailUtils._extract_header_value(pipeline_ref_raw)
            pipeline_status = EmailUtils._extract_header_value(pipeline_status_raw)

            # Optional fields
            pipeline_url = EmailUtils._extract_header_value(pipeline_url_raw)
            project_url = EmailUtils._extract_header_value(project_url_raw)
            commit_sha = EmailUtils._extract_header_value(commit_sha_raw)

            # Clean and validate values
            cleaned_headers = EmailUtils._clean_gitlab_headers({
                "project_id": project_id,
                "project_name": project_name,
                "project_path": project_path,
                "pipeline_id": pipeline_id,
                "pipeline_ref": pipeline_ref,
                "pipeline_status": pipeline_status,
                "pipeline_url": pipeline_url,
                "project_url": project_url,
                "commit_sha": commit_sha
            })

            # Validate required fields
            validation_error = EmailUtils._validate_gitlab_headers(cleaned_headers)
            if validation_error:
                return None, validation_error

            return cleaned_headers, None

        except Exception as e:
            logger.error(
                "Failed to extract GitLab headers",
                error=str(e),
                message_uid=getattr(msg, 'uid', 'unknown')
            )
            return None, f"Failed to extract GitLab headers: {str(e)}"

    @staticmethod
    def _clean_gitlab_headers(headers: Dict[str, Any]) -> Dict[str, str]:
        """Clean and normalize GitLab headers."""
        cleaned = {}
        
        for key, value in headers.items():
            if value is not None:
                # Convert to string and strip whitespace
                cleaned_value = str(value).strip()
                
                # Special handling for pipeline_status
                if key == "pipeline_status":
                    cleaned_value = cleaned_value.lower()
                
                # Only include non-empty values
                if cleaned_value:
                    cleaned[key] = cleaned_value
            else:
                cleaned[key] = None
                
        return cleaned

    @staticmethod
    def _validate_gitlab_headers(headers: Dict[str, str]) -> Optional[str]:
        """Validate GitLab headers for required fields and data integrity."""
        # Check required fields
        required_fields = ["project_id", "pipeline_id"]
        missing_fields = [field for field in required_fields if not headers.get(field)]
        
        if missing_fields:
            return f"Missing required GitLab headers: {', '.join(missing_fields)}"

        # Validate data types and formats
        try:
            # project_id and pipeline_id should be valid integers
            int(headers["project_id"])
            int(headers["pipeline_id"])
        except (ValueError, TypeError):
            return "Invalid project_id or pipeline_id format (must be numeric)"

        # Validate pipeline status
        valid_statuses = [
            "pending", "running", "success", "failed", "canceled", 
            "skipped", "manual", "scheduled", "created"
        ]
        pipeline_status = headers.get("pipeline_status", "").lower()
        if pipeline_status and pipeline_status not in valid_statuses:
            logger.warning(
                "Unknown pipeline status",
                status=pipeline_status,
                valid_statuses=valid_statuses
            )
            # Don't fail validation for unknown status, just log warning

        return None  # No validation errors

    @staticmethod
    def _extract_header_value(header_value: Any) -> Optional[str]:
        """Extract string value from email header (which might be a tuple).
        
        Email headers can be returned as tuples in some cases. This method
        safely extracts the first value from a tuple or returns the value as-is.
        
        Args:
            header_value: Raw header value from email (could be str, tuple, or None)
            
        Returns:
            String value if found, None if header_value is None or empty tuple
            
        Examples:
            >>> EmailUtils._extract_header_value(("value1", "value2"))
            "value1"
            >>> EmailUtils._extract_header_value("simple_value")
            "simple_value"
            >>> EmailUtils._extract_header_value(None)
            None
        """
        if isinstance(header_value, tuple) and header_value:
            return header_value[0]
        return header_value

    @staticmethod
    def create_webhook_from_email(
        msg: Any, 
        gitlab_headers: Dict[str, str]
    ) -> GitLabWebhook:
        """Convert email message to GitLab webhook format.

        Creates a GitLabWebhook object that matches the structure expected by
        the orchestration service, allowing email-sourced events to be processed
        through the same pipeline as direct webhook events.

        Args:
            msg: Email message object with .from_ attribute
            gitlab_headers: GitLab headers dictionary as returned by extract_gitlab_headers()
                Must contain at least 'project_id' and 'pipeline_id' keys

        Returns:
            GitLabWebhook object compatible with orchestration service processing

        Raises:
            ValueError: If gitlab_headers contains invalid data (non-numeric IDs, etc.)
            KeyError: If required header fields are missing

        Examples:
            >>> headers, _ = EmailUtils.extract_gitlab_headers(msg)
            >>> webhook = EmailUtils.create_webhook_from_email(msg, headers)
            >>> print(webhook.project.id)  # Numeric project ID
        """
        try:
            return GitLabWebhook(
                object_kind=GitLabEventType.PIPELINE,
                project=GitLabProject(
                    id=int(gitlab_headers["project_id"]),
                    name=gitlab_headers["project_name"] or f"Project-{gitlab_headers['project_id']}",
                    web_url=EmailUtils._build_project_web_url(gitlab_headers),
                    namespace="email-source",
                    path_with_namespace=gitlab_headers["project_path"] or f"email-source/project-{gitlab_headers['project_id']}",
                    default_branch="main"
                ),
                object_attributes=GitLabWebhookObjectAttributes(
                    id=int(gitlab_headers["pipeline_id"]),
                    status=gitlab_headers["pipeline_status"]
                ),
                user=GitLabUser(
                    id=0,
                    name="Email System",
                    username="email-system",
                    email=msg.from_
                )
            )
        except (ValueError, KeyError) as e:
            logger.error(
                "Failed to create webhook from email",
                error=str(e),
                gitlab_headers=gitlab_headers
            )
            raise ValueError(f"Invalid GitLab headers for webhook creation: {e}")

    @staticmethod
    def _build_project_web_url(gitlab_headers: Dict[str, str]) -> str:
        """Build project web URL from GitLab headers.
        
        Creates a web URL to the GitLab project, preferring the project_path
        if available, falling back to a generic project URL format.
        
        Args:
            gitlab_headers: Dictionary containing GitLab header information
            
        Returns:
            Complete HTTPS URL to the GitLab project
            
        Examples:
            >>> headers = {"project_path": "user/project", "project_id": "123"}
            >>> EmailUtils._build_project_web_url(headers)
            "https://gitlab.com/user/project"
            >>> headers = {"project_id": "123"}
            >>> EmailUtils._build_project_web_url(headers)
            "https://gitlab.com/project/123"
        """
        if gitlab_headers.get('project_path'):
            return f"https://gitlab.com/{gitlab_headers['project_path']}"
        return f"https://gitlab.com/project/{gitlab_headers['project_id']}"

    @staticmethod
    def create_processed_email_record(msg: Any) -> ProcessedEmail:
        """Create ProcessedEmail database record from message.

        Converts an email message into a ProcessedEmail database model instance
        with basic information extracted and status set to 'pending' for further
        processing by the orchestration service.

        Args:
            msg: Email message object with attributes:
                - .uid: Unique identifier for the message
                - .headers: Dictionary/mapping of email headers
                - .date: Email timestamp
                - .from_: Sender email address
                - .subject: Email subject line

        Returns:
            ProcessedEmail instance ready for database insertion

        Raises:
            ValueError: If required email attributes are missing or invalid
            
        Examples:
            >>> record = EmailUtils.create_processed_email_record(email_msg)
            >>> print(record.status)  # "pending"
            >>> print(record.message_uid)  # Email UID
        """
        try:
            # Extract message_id from headers
            message_id = EmailUtils._extract_message_id(msg)

            return ProcessedEmail(
                message_uid=str(msg.uid),
                message_id=message_id,
                received_at=msg.date.astimezone(timezone.utc).replace(tzinfo=None),
                from_email=msg.from_,
                subject=msg.subject,
                status="pending"
            )
        except Exception as e:
            logger.error(
                "Failed to create processed email record",
                error=str(e),
                message_uid=getattr(msg, 'uid', 'unknown')
            )
            raise ValueError(f"Failed to create email record: {e}")

    @staticmethod
    def _extract_message_id(msg: Any) -> Optional[str]:
        """Extract message ID from email headers.
        
        Gets the standard Message-ID header from the email, handling
        tuple format if necessary.
        
        Args:
            msg: Email message object with .headers attribute
            
        Returns:
            Message ID string if found, None otherwise
            
        Note:
            Message-ID is used for duplicate detection and email tracking
        """
        message_id_raw = msg.headers.get("message-id")
        if isinstance(message_id_raw, tuple) and message_id_raw:
            return message_id_raw[0]
        return message_id_raw

    @staticmethod
    def get_imap_connection() -> MailBox:
        """Get IMAP connection for email checking.

        Creates and authenticates an IMAP connection using settings from
        the application configuration. This is used by the orchestration
        service for email monitoring.

        Returns:
            Connected and authenticated MailBox instance

        Raises:
            ConnectionError: If IMAP connection or authentication fails
            
        Note:
            The returned MailBox should be used in a context manager or
            manually closed to prevent connection leaks.
            
        Examples:
            >>> with EmailUtils.get_imap_connection() as mailbox:
            ...     messages = mailbox.fetch()
        """
        try:
            mailbox = MailBox(settings.imap_server)
            mailbox.login(settings.imap_user, settings.imap_app_password)
            return mailbox
        except Exception as e:
            logger.error(
                "Failed to connect to IMAP server",
                server=settings.imap_server,
                username=settings.imap_user,
                error=str(e)
            )
            raise ConnectionError(f"IMAP connection failed: {e}")

    @staticmethod
    def validate_email_for_processing(msg: Any) -> Tuple[bool, Optional[str]]:
        """Validate if email is suitable for processing.

        Args:
            msg: Email message object

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            # Check required attributes
            if not hasattr(msg, 'uid') or not msg.uid:
                return False, "Email missing UID"

            if not hasattr(msg, 'from_') or not msg.from_:
                return False, "Email missing sender"

            if not hasattr(msg, 'subject') or not msg.subject:
                return False, "Email missing subject"

            if not hasattr(msg, 'date') or not msg.date:
                return False, "Email missing date"

            # Check if email is from configured GitLab email
            expected_gitlab_email = settings.imap_gitlab_email
            if expected_gitlab_email and msg.from_ != expected_gitlab_email:
                return False, f"Email not from configured GitLab email (expected: {expected_gitlab_email}, got: {msg.from_})"

            # Check if subject contains failure indicators
            failure_keywords = [
                'failed', 'failure', 'error', 'exception', 
                'job failed', 'pipeline failed', 'build failed'
            ]
            subject_lower = msg.subject.lower()
            if not any(keyword in subject_lower for keyword in failure_keywords):
                return False, "Email subject doesn't indicate failure"

            return True, None

        except Exception as e:
            logger.error("Email validation failed", error=str(e))
            return False, f"Validation error: {e}"

    @staticmethod
    def extract_email_content(msg: Any) -> Dict[str, Optional[str]]:
        """Extract email content (text and HTML).

        Args:
            msg: Email message object

        Returns:
            Dict with 'text' and 'html' content
        """
        try:
            content = {
                'text': None,
                'html': None
            }

            # Extract HTML content if available
            if hasattr(msg, 'html') and msg.html:
                content['html'] = str(msg.html).strip()

            # Extract text content if available
            if hasattr(msg, 'text') and msg.text:
                content['text'] = str(msg.text).strip()

            # If no content found, try alternative methods
            if not content['html'] and not content['text']:
                logger.warning(
                    "No email content found",
                    message_uid=getattr(msg, 'uid', 'unknown')
                )

            return content

        except Exception as e:
            logger.error(
                "Failed to extract email content",
                error=str(e),
                message_uid=getattr(msg, 'uid', 'unknown')
            )
            return {'text': None, 'html': None}

    @staticmethod
    def is_duplicate_email(processed_email: ProcessedEmail) -> bool:
        """Check if this email represents a duplicate based on content similarity.
        
        This is a basic implementation - could be enhanced with more sophisticated
        duplicate detection algorithms.

        Args:
            processed_email: ProcessedEmail instance to check

        Returns:
            True if likely duplicate, False otherwise
        """
        try:
            # Basic duplicate detection based on project+pipeline combination
            if (processed_email.project_id and 
                processed_email.pipeline_id and 
                processed_email.pipeline_status):
                return False  # Has unique GitLab identifiers, probably not duplicate

            # Could add more sophisticated duplicate detection here:
            # - Content similarity analysis
            # - Time-based analysis
            # - Subject line analysis
            
            return False

        except Exception as e:
            logger.error(
                "Duplicate check failed",
                error=str(e),
                email_id=getattr(processed_email, 'id', 'unknown')
            )
            return False


class EmailMonitoringService:
    """DEPRECATED: Use OrchestrationService with email monitoring instead.

    This class is kept for backwards compatibility but raises an error
    to encourage migration to the new architecture where OrchestrationService
    handles email monitoring directly.
    """

    def __init__(self, *args, **kwargs):
        logger.warning(
            "EmailMonitoringService is deprecated. Use OrchestrationService instead."
        )
        raise DeprecationWarning(
            "EmailMonitoringService is deprecated. "
            "Use OrchestrationService.start_email_monitoring() instead. "
            "The orchestrator now handles email monitoring as part of its unified workflow."
        )