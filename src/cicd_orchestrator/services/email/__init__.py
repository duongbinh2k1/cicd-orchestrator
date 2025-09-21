"""Email processing module.

This module provides email processing functionality with clean separation of concerns:
- client: IMAP connection management with proxy support
- parser: Email parsing and validation logic  
- converter: Email to GitLab webhook conversion
- service: High-level email processing orchestration

Example:
    from .service import EmailService
    
    # Get IMAP connection
    with EmailService.get_imap_connection() as mailbox:
        messages = mailbox.fetch()
        
    # Process email
    headers, error = EmailService.extract_gitlab_headers(msg)
    webhook = EmailService.create_webhook_from_email(msg, headers)
"""

from .service import EmailUtils, EmailMonitoringService

__all__ = ['EmailUtils', 'EmailMonitoringService']