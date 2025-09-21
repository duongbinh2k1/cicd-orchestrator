"""GitLab webhook conversion utilities.

This module handles conversion of email messages and GitLab headers into
GitLab webhook format for processing by the orchestration service.

Classes:
    GitLabWebhookConverter: Convert emails to webhook format
    ProcessedEmailFactory: Create ProcessedEmail database records
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any

import structlog

from ...models.email import ProcessedEmail
from ...models.gitlab import (
    GitLabWebhook, 
    GitLabEventType, 
    GitLabWebhookObjectAttributes, 
    GitLabProject, 
    GitLabUser
)

logger = structlog.get_logger(__name__)


class GitLabWebhookConverter:
    """Convert email messages to GitLab webhook format."""
    
    @staticmethod
    def create_webhook_from_email(msg: Any, gitlab_headers: Dict[str, str]) -> GitLabWebhook:
        """Convert email message to GitLab webhook format.

        Creates a GitLabWebhook object that matches the structure expected by
        the orchestration service, allowing email-sourced events to be processed
        through the same pipeline as direct webhook events.

        Args:
            msg: Email message object with .from_ attribute
            gitlab_headers: GitLab headers dictionary as returned by extract_gitlab_headers()

        Returns:
            GitLabWebhook object compatible with orchestration service processing

        Raises:
            ValueError: If gitlab_headers contains invalid data
            KeyError: If required header fields are missing
        """
        try:
            return GitLabWebhook(
                object_kind=GitLabEventType.PIPELINE,
                project=GitLabProject(
                    id=int(gitlab_headers["project_id"]),
                    name=gitlab_headers.get("project_name") or f"Project-{gitlab_headers['project_id']}",
                    web_url=GitLabWebhookConverter._build_project_web_url(gitlab_headers),
                    namespace="email-source",
                    path_with_namespace=gitlab_headers.get("project_path") or f"email-source/project-{gitlab_headers['project_id']}",
                    default_branch="main"
                ),
                object_attributes=GitLabWebhookObjectAttributes(
                    id=int(gitlab_headers["pipeline_id"]),
                    status=gitlab_headers.get("pipeline_status")
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
        """
        if gitlab_headers.get('project_path'):
            return f"https://gitlab.com/{gitlab_headers['project_path']}"
        return f"https://gitlab.com/project/{gitlab_headers['project_id']}"


class ProcessedEmailFactory:
    """Create ProcessedEmail database records from email messages."""
    
    @staticmethod
    def create_from_message(msg: Any) -> ProcessedEmail:
        """Create ProcessedEmail database record from message.

        Converts an email message into a ProcessedEmail database model instance
        with basic information extracted and status set to 'pending' for further
        processing by the orchestration service.

        Args:
            msg: Email message object with required attributes

        Returns:
            ProcessedEmail instance ready for database insertion

        Raises:
            ValueError: If required email attributes are missing or invalid
        """
        try:
            # Extract message_id from headers
            message_id = ProcessedEmailFactory._extract_message_id(msg)

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
        """
        # Create case-insensitive header lookup
        headers_lower = {k.lower(): v for k, v in msg.headers.items()}
        message_id_raw = headers_lower.get("message-id")
        if isinstance(message_id_raw, tuple) and message_id_raw:
            return message_id_raw[0]
        return message_id_raw