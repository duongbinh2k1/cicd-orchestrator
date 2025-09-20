"""Logging configuration for the CI/CD Orchestrator."""

import logging
import logging.config
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from .config import settings


def setup_logging(
    log_level: Optional[str] = None,
    log_format: Optional[str] = None,
    log_file: Optional[str] = None,
) -> None:
    """Setup logging configuration.
    
    Args:
        log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Log format (json, console)
        log_file: Optional log file path
    """
    log_level = log_level or settings.log_level
    log_format = log_format or settings.log_format
    log_file = log_file or settings.log_file
    
    # Configure structlog
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    
    if log_format == "json":
        # JSON format for production
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
        )
    else:
        # Console format for development
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.dev.ConsoleRenderer(colors=True),
        ]
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(colors=True),
        )
    
    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging
    handlers = ["console"]
    if log_file:
        handlers.append("file")
    
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "structured": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processor": processors[-1],
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": "structured",
            },
        },
        "loggers": {
            "": {
                "handlers": handlers,
                "level": log_level,
                "propagate": True,
            },
            "uvicorn": {
                "handlers": handlers,
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": handlers,
                "level": "INFO",
                "propagate": False,
            },
            "httpx": {
                "handlers": handlers,
                "level": "WARNING",
                "propagate": False,
            },
            "openai": {
                "handlers": handlers,
                "level": "WARNING",
                "propagate": False,
            },
            "anthropic": {
                "handlers": handlers,
                "level": "WARNING",
                "propagate": False,
            },
        },
    }
    
    # Add file handler if log file is specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        logging_config["handlers"]["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(log_path),
            "maxBytes": 10 * 1024 * 1024,  # 10MB
            "backupCount": 5,
            "formatter": "structured",
        }
    
    logging.config.dictConfig(logging_config)
    
    # Log setup completion
    logger = structlog.get_logger(__name__)
    logger.info(f"Logging configured: level={log_level}, format={log_format}")
    if log_file:
        logger.info(f"Log file: {log_file}")


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.
    
    Args:
        name: Logger name (usually __name__)
        
    Returns:
        Structured logger instance
    """
    return structlog.get_logger(name)


def configure_uvicorn_logging() -> Dict[str, Any]:
    """Configure uvicorn logging.
    
    Returns:
        Uvicorn logging configuration
    """
    log_level = settings.log_level.lower()
    
    if settings.log_format == "json":
        formatter = {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": "%(levelprefix)s %(message)s",
            "use_colors": False,
        }
    else:
        formatter = {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": "%(levelprefix)s %(message)s",
            "use_colors": True,
        }
    
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": formatter,
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": log_level.upper()},
            "uvicorn.error": {"level": log_level.upper()},
            "uvicorn.access": {"handlers": ["access"], "level": log_level.upper(), "propagate": False},
        },
    }


def log_request_response(
    logger: structlog.stdlib.BoundLogger,
    request_id: str,
    method: str,
    url: str,
    status_code: int,
    duration_ms: float,
    **kwargs
) -> None:
    """Log HTTP request/response details.
    
    Args:
        logger: Logger instance
        request_id: Unique request ID
        method: HTTP method
        url: Request URL
        status_code: Response status code
        duration_ms: Request duration in milliseconds
        **kwargs: Additional context
    """
    logger.info(
        "HTTP request completed",
        request_id=request_id,
        method=method,
        url=url,
        status_code=status_code,
        duration_ms=duration_ms,
        **kwargs
    )


def log_ai_analysis(
    logger: structlog.stdlib.BoundLogger,
    request_id: str,
    provider: str,
    model: str,
    tokens_used: Optional[int],
    duration_ms: int,
    success: bool,
    **kwargs
) -> None:
    """Log AI analysis details.
    
    Args:
        logger: Logger instance
        request_id: Unique request ID
        provider: AI provider name
        model: AI model name
        tokens_used: Number of tokens used
        duration_ms: Analysis duration in milliseconds
        success: Whether analysis was successful
        **kwargs: Additional context
    """
    logger.info(
        "AI analysis completed",
        request_id=request_id,
        provider=provider,
        model=model,
        tokens_used=tokens_used,
        duration_ms=duration_ms,
        success=success,
        **kwargs
    )


def log_gitlab_api_call(
    logger: structlog.stdlib.BoundLogger,
    method: str,
    endpoint: str,
    status_code: int,
    duration_ms: float,
    **kwargs
) -> None:
    """Log GitLab API call details.
    
    Args:
        logger: Logger instance
        method: HTTP method
        endpoint: API endpoint
        status_code: Response status code
        duration_ms: Request duration in milliseconds
        **kwargs: Additional context
    """
    logger.info(
        "GitLab API call completed",
        method=method,
        endpoint=endpoint,
        status_code=status_code,
        duration_ms=duration_ms,
        **kwargs
    )
