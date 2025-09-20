"""Exception handlers for the FastAPI application."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
import structlog

from .exceptions import OrchestrationError

logger = structlog.get_logger(__name__)


def configure_exception_handlers(app: FastAPI) -> None:
    """Configure exception handlers for the application."""
    
    @app.exception_handler(OrchestrationError)
    async def orchestration_exception_handler(request: Request, exc: OrchestrationError) -> JSONResponse:
        """Handle orchestration exceptions."""
        logger.error(
            "Orchestration error",
            error=str(exc),
            error_code=exc.error_code,
            path=request.url.path,
            method=request.method,
        )
        
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.error_code or "orchestration_error",
                "message": str(exc),
                "details": exc.details,
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle general exceptions."""
        logger.error(
            "Unhandled exception",
            error=str(exc),
            path=request.url.path,
            method=request.method,
            exc_info=True,
        )
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Internal Server Error",
                "message": "An unexpected error occurred",
            },
        )

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc) -> JSONResponse:
        """Handle 404 errors."""
        logger.warning(
            "Resource not found",
            path=request.url.path,
            method=request.method,
        )
        
        return JSONResponse(
            status_code=404,
            content={
                "error": "Not Found",
                "message": f"The requested resource {request.url.path} was not found",
            },
        )

    @app.exception_handler(405)
    async def method_not_allowed_handler(request: Request, exc) -> JSONResponse:
        """Handle 405 errors."""
        logger.warning(
            "Method not allowed",
            path=request.url.path,
            method=request.method,
        )
        
        return JSONResponse(
            status_code=405,
            content={
                "error": "Method Not Allowed",
                "message": f"Method {request.method} is not allowed for {request.url.path}",
            },
        )

    logger.info("Exception handlers configured")
