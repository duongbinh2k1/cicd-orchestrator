"""Email parsing utilities for GitLab pipeline notifications.

This module provides pure email parsing functionality - header extraction,
content parsing, and validation logic without any connection management.

Classes:
    GitLabEmailParser: Parse GitLab-specific email headers and content
    EmailContentExtractor: Extract email text/HTML content
    EmailValidator: Validate emails for processing
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Tuple, Any

import structlog

from ...core.config import settings

logger = structlog.get_logger(__name__)


class GitLabEmailParser:
    """Parser for GitLab pipeline notification emails."""
    
    @staticmethod
    def extract_gitlab_headers(msg: Any) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
        """Extract GitLab headers from email message.

        Args:
            msg: Email message object from imap_tools library

        Returns:
            Tuple containing:
                - gitlab_headers_dict: Dictionary with GitLab information if successful, 
                  None if extraction failed
                - error_message: Error description if extraction failed, None if successful
        """
        try:
            headers = dict(msg.headers)
            
            # Debug logging: Print all available headers
            logger.debug(
                "Extracting GitLab headers - all email headers",
                message_uid=getattr(msg, 'uid', 'unknown'),
                subject=getattr(msg, 'subject', 'unknown'),
                from_email=getattr(msg, 'from_', 'unknown'),
                all_headers=list(headers.keys()),
                header_count=len(headers)
            )

            # Create case-insensitive header lookup
            headers_lower = {k.lower(): v for k, v in headers.items()}

            # Extract raw header values (using lowercase keys)
            raw_headers = {
                "project_id": headers_lower.get("x-gitlab-project-id"),
                "project_name": headers_lower.get("x-gitlab-project"),
                "project_path": headers_lower.get("x-gitlab-project-path"),
                "pipeline_id": headers_lower.get("x-gitlab-pipeline-id"),
                "pipeline_ref": headers_lower.get("x-gitlab-pipeline-ref"),
                "pipeline_status": headers_lower.get("x-gitlab-pipeline-status", ""),
                "pipeline_url": headers_lower.get("x-gitlab-pipeline-url"),
                "project_url": headers_lower.get("x-gitlab-project-url"),
                "commit_sha": headers_lower.get("x-gitlab-commit-sha")
            }
            
            # Debug logging: Show which GitLab headers were found
            found_headers = {k: v for k, v in raw_headers.items() if v is not None}
            logger.debug(
                "GitLab headers extraction",
                message_uid=getattr(msg, 'uid', 'unknown'),
                found_gitlab_headers=found_headers,
                found_count=len(found_headers)
            )

            # Convert tuple to string if needed and clean values
            cleaned_headers = {}
            for key, value in raw_headers.items():
                cleaned_value = GitLabEmailParser._extract_header_value(value)
                if cleaned_value is not None:  # Include empty strings too
                    # Special handling for pipeline_status
                    if key == "pipeline_status":
                        cleaned_value = cleaned_value.lower()
                    cleaned_headers[key] = cleaned_value.strip() if isinstance(cleaned_value, str) else str(cleaned_value)

            # Validate required fields
            validation_error = GitLabEmailParser._validate_gitlab_headers(cleaned_headers)
            if validation_error:
                logger.warning(
                    "GitLab headers validation failed",
                    message_uid=getattr(msg, 'uid', 'unknown'),
                    subject=getattr(msg, 'subject', 'unknown'),
                    cleaned_headers=cleaned_headers,
                    validation_error=validation_error
                )
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
    def _extract_header_value(header_value: Any) -> Optional[str]:
        """Extract string value from email header (which might be a tuple)."""
        if isinstance(header_value, tuple) and header_value:
            return header_value[0]
        return header_value

    @staticmethod
    def _validate_gitlab_headers(headers: Dict[str, str]) -> Optional[str]:
        """Validate GitLab headers for required fields and data integrity."""
        # Check required fields
        required_fields = ["project_id", "pipeline_id"]
        missing_fields = [field for field in required_fields if not headers.get(field)]
        
        logger.debug(
            "Validating GitLab headers",
            headers=headers,
            required_fields=required_fields,
            missing_fields=missing_fields
        )
        
        if missing_fields:
            return f"Missing required GitLab headers: {', '.join(missing_fields)}"

        # Validate data types and formats
        try:
            # project_id and pipeline_id should be valid integers
            int(headers["project_id"])
            int(headers["pipeline_id"])
            logger.debug("GitLab headers validation passed", project_id=headers["project_id"], pipeline_id=headers["pipeline_id"])
        except (ValueError, TypeError) as e:
            logger.debug(
                "GitLab headers validation failed - invalid format",
                project_id=headers.get("project_id"),
                pipeline_id=headers.get("pipeline_id"),
                error=str(e)
            )
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
    def extract_message_id(msg: Any) -> Optional[str]:
        """Extract message ID from email headers."""
        message_id_raw = msg.headers.get("message-id")
        if isinstance(message_id_raw, tuple) and message_id_raw:
            return message_id_raw[0]
        return message_id_raw


class EmailContentExtractor:
    """Extract content from email messages."""
    
    @staticmethod
    def extract_content(msg: Any) -> Dict[str, Optional[str]]:
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


class EmailValidator:
    """Validate emails for processing."""
    
    @staticmethod
    def validate_for_processing(msg: Any) -> Tuple[bool, Optional[str]]:
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
            if expected_gitlab_email:
                actual_email = EmailValidator._extract_email_address(msg.from_)
                if actual_email != expected_gitlab_email:
                    return False, f"Email not from configured GitLab email (expected: {expected_gitlab_email}, got: {actual_email})"

            # Check if subject contains failure indicators
            failure_keywords_str = settings.email_failure_keywords
            failure_keywords = [kw.strip() for kw in failure_keywords_str.split(',') if kw.strip()]
            subject_lower = msg.subject.lower()
            if not any(keyword in subject_lower for keyword in failure_keywords):
                return False, "Email subject doesn't indicate failure"

            return True, None

        except Exception as e:
            logger.error("Email validation failed", error=str(e))
            return False, f"Validation error: {e}"

    @staticmethod
    def _extract_email_address(from_field: str) -> str:
        """Extract email address from 'Display Name <email@domain.com>' format.
        
        Args:
            from_field: The email from field which might contain display name
            
        Returns:
            The extracted email address, or original string if no extraction needed
        """
        import re
        if not from_field:
            return ""
            
        # Check if format is "Display Name <email@domain.com>"
        match = re.search(r'<([^>]+)>', from_field)
        if match:
            return match.group(1).strip()
        
        # If no angle brackets, assume it's already just the email
        return from_field.strip()

    @staticmethod
    def is_duplicate_email(processed_email) -> bool:
        """Check if this email represents a duplicate.
        
        Args:
            processed_email: ProcessedEmail instance to check

        Returns:
            True if likely duplicate, False otherwise
        """
        try:
            # Basic duplicate detection based on project+pipeline combination
            if (hasattr(processed_email, 'project_id') and processed_email.project_id and 
                hasattr(processed_email, 'pipeline_id') and processed_email.pipeline_id and 
                hasattr(processed_email, 'pipeline_status') and processed_email.pipeline_status):
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