"""Custom exceptions for the CI/CD Orchestrator."""


class OrchestrationError(Exception):
    """Base exception for orchestration errors."""

    def __init__(self, message: str, error_code: str = None, details: dict = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}


class ConfigurationError(OrchestrationError):
    """Exception raised for configuration errors."""

    def __init__(self, message: str, config_key: str = None):
        super().__init__(message, error_code="CONFIGURATION_ERROR")
        self.config_key = config_key


class GitLabAPIError(OrchestrationError):
    """Exception raised for GitLab API errors."""

    def __init__(self, message: str, status_code: int = None, response_data: dict = None):
        super().__init__(
            message,
            error_code="GITLAB_API_ERROR",
            details={"status_code": status_code, "response_data": response_data}
        )
        self.status_code = status_code
        self.response_data = response_data


class AIServiceError(OrchestrationError):
    """Exception raised for AI service errors."""

    def __init__(self, message: str, provider: str = None, model: str = None):
        super().__init__(
            message,
            error_code="AI_SERVICE_ERROR",
            details={"provider": provider, "model": model}
        )
        self.provider = provider
        self.model = model


class WebhookValidationError(OrchestrationError):
    """Exception raised for webhook validation errors."""

    def __init__(self, message: str, webhook_type: str = None):
        super().__init__(
            message,
            error_code="WEBHOOK_VALIDATION_ERROR",
            details={"webhook_type": webhook_type}
        )
        self.webhook_type = webhook_type


class AnalysisTimeoutError(OrchestrationError):
    """Exception raised when analysis times out."""

    def __init__(self, message: str, timeout_seconds: int = None):
        super().__init__(
            message,
            error_code="ANALYSIS_TIMEOUT_ERROR",
            details={"timeout_seconds": timeout_seconds}
        )
        self.timeout_seconds = timeout_seconds


class RateLimitError(OrchestrationError):
    """Exception raised when rate limit is exceeded."""

    def __init__(self, message: str, limit: int = None, window_seconds: int = None):
        super().__init__(
            message,
            error_code="RATE_LIMIT_ERROR",
            details={"limit": limit, "window_seconds": window_seconds}
        )
        self.limit = limit
        self.window_seconds = window_seconds


class ValidationError(OrchestrationError):
    """Exception raised for validation errors."""

    def __init__(self, message: str, field: str = None, value: str = None):
        super().__init__(
            message,
            error_code="VALIDATION_ERROR",
            details={"field": field, "value": value}
        )
        self.field = field
        self.value = value


class DatabaseError(OrchestrationError):
    """Exception raised for database errors."""

    def __init__(self, message: str, operation: str = None):
        super().__init__(
            message,
            error_code="DATABASE_ERROR",
            details={"operation": operation}
        )
        self.operation = operation


class AuthenticationError(OrchestrationError):
    """Exception raised for authentication errors."""

    def __init__(self, message: str, auth_type: str = None):
        super().__init__(
            message,
            error_code="AUTHENTICATION_ERROR",
            details={"auth_type": auth_type}
        )
        self.auth_type = auth_type


class AuthorizationError(OrchestrationError):
    """Exception raised for authorization errors."""

    def __init__(self, message: str, resource: str = None, action: str = None):
        super().__init__(
            message,
            error_code="AUTHORIZATION_ERROR",
            details={"resource": resource, "action": action}
        )
        self.resource = resource
        self.action = action
