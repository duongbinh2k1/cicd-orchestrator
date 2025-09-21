"""Business services and external clients.

This module contains:
- Business logic services (orchestration_service.py)
- External API clients (gitlab_client.py) 
- AI provider integrations (ai_service.py)
- Email processing module (email/)

Naming convention:
- *_service.py: Business logic layer
- *_client.py: External API integration layer
- *_provider.py: Specific implementations within services
"""

from .gitlab import GitLabClient, GitLabAPIError
from .email import EmailUtils

__all__ = ["GitLabClient", "GitLabAPIError", "EmailUtils"]
