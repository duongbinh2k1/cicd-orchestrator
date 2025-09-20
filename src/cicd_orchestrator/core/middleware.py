"""FastAPI middleware configuration."""

import time
import uuid
from typing import List

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import structlog

from .config import settings

logger = structlog.get_logger(__name__)


def configure_cors(app: FastAPI) -> None:
    """Configure CORS middleware."""
    if settings.cors_origins != "*":
        origins = [origin.strip() for origin in settings.cors_origins.split(",")]
    else:
        origins = ["*"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    logger.info("CORS middleware configured", allowed_origins=origins[:3] if len(origins) > 3 else origins)


def add_custom_middleware(app: FastAPI) -> None:
    """Add custom middleware to the application."""
    
    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next):
        """Add process time header to responses."""
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        return response

    @app.middleware("http")
    async def add_request_id_header(request: Request, call_next):
        """Add request ID header to responses."""
        request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """Log incoming requests."""
        start_time = time.time()
        
        logger.debug(
            "Request started",
            method=request.method,
            url=str(request.url),
            headers=dict(request.headers),
        )
        
        response = await call_next(request)
        
        process_time = time.time() - start_time
        logger.info(
            "Request completed",
            method=request.method,
            url=str(request.url),
            status_code=response.status_code,
            process_time=round(process_time, 4),
        )
        
        return response

    logger.info("Custom middleware configured")


def configure_middleware(app: FastAPI) -> None:
    """Configure all middleware for the application."""
    configure_cors(app)
    add_custom_middleware(app)
