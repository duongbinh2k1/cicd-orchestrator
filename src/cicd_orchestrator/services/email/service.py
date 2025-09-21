"""Email service orchestration layer.

This module provides a thin orchestration layer for email processing,
delegating specific tasks to specialized modules:
- IMAP connection management -> imap_client.py
- Email parsing -> email_parser.py  
- GitLab webhook conversion -> gitlab_converter.py

Classes:
    EmailUtils: High-level email processing orchestration
    EmailMonitoringService: Deprecated service class (raises DeprecationWarning)
"""

from typing import Optional, Dict, Tuple, Any

import structlog

from .client import IMAPClient
from .parser import GitLabEmailParser, EmailContentExtractor, EmailValidator
from .converter import GitLabWebhookConverter, ProcessedEmailFactory
from ...models.email import ProcessedEmail
from ...models.gitlab import GitLabWebhook

logger = structlog.get_logger(__name__)


class EmailUtils:
    """High-level email processing orchestration.
    
    This class provides a simplified interface for email processing by
    delegating to specialized modules. All methods are static and stateless.
    """

    @staticmethod
    def get_imap_connection():
        """Get IMAP connection with optional proxy support.
        
        Returns:
            Connected and authenticated MailBox instance
            
        Raises:
            ConnectionError: If IMAP connection or authentication fails
        """
        return IMAPClient.get_connection()

    @staticmethod
    def extract_gitlab_headers(msg: Any) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
        """Extract GitLab headers from email message.

        Args:
            msg: Email message object from imap_tools library

        Returns:
            Tuple of (gitlab_headers_dict, error_message)
        """
        return GitLabEmailParser.extract_gitlab_headers(msg)

    @staticmethod
    def create_webhook_from_email(msg: Any, gitlab_headers: Dict[str, str]) -> GitLabWebhook:
        """Convert email message to GitLab webhook format.

        Args:
            msg: Email message object
            gitlab_headers: GitLab headers dictionary

        Returns:
            GitLabWebhook object compatible with orchestration service processing
        """
        return GitLabWebhookConverter.create_webhook_from_email(msg, gitlab_headers)

    @staticmethod
    def create_processed_email_record(msg: Any) -> ProcessedEmail:
        """Create ProcessedEmail database record from message.

        Args:
            msg: Email message object

        Returns:
            ProcessedEmail instance ready for database insertion
        """
        return ProcessedEmailFactory.create_from_message(msg)

    @staticmethod
    def validate_email_for_processing(msg: Any) -> Tuple[bool, Optional[str]]:
        """Validate if email is suitable for processing.

        Args:
            msg: Email message object

        Returns:
            Tuple of (is_valid, error_message)
        """
        return EmailValidator.validate_for_processing(msg)

    @staticmethod
    def extract_email_content(msg: Any) -> Dict[str, Optional[str]]:
        """Extract email content (text and HTML).

        Args:
            msg: Email message object

        Returns:
            Dict with 'text' and 'html' content
        """
        return EmailContentExtractor.extract_content(msg)

    @staticmethod
    def is_duplicate_email(processed_email: ProcessedEmail) -> bool:
        """Check if this email represents a duplicate.

        Args:
            processed_email: ProcessedEmail instance to check

        Returns:
            True if likely duplicate, False otherwise
        """
        return EmailValidator.is_duplicate_email(processed_email)


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