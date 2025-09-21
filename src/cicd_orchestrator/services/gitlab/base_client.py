"""Base HTTP client for GitLab API operations."""

import asyncio
from typing import Any, Dict, Optional

import httpx
import structlog

from ...core.config import settings
from ...core.exceptions import GitLabAPIError

logger = structlog.get_logger(__name__)


class BaseClient:
    """Base HTTP client for GitLab API."""

    def __init__(
        self,
        base_url: str = "https://gitlab.com",
        api_token: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        """Initialize base client.
        
        Args:
            base_url: GitLab instance base URL
            api_token: GitLab API token
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
        """
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}/api/v4"
        self.api_token = api_token or settings.gitlab_api_token
        self.timeout = timeout
        self.max_retries = max_retries
        
        self._session: Optional[httpx.AsyncClient] = None
        self._original_proxy_env: Dict[str, str] = {}
        
        if not self.api_token:
            raise ValueError("GitLab API token is required")

    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def _ensure_session(self) -> httpx.AsyncClient:
        """Ensure HTTP session is available."""
        if self._session is None or self._session.is_closed:
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
                "User-Agent": "cicd-orchestrator/1.0",
            }
            
            # Configure client settings
            client_kwargs = {
                "base_url": self.api_url,
                "headers": headers,
                "timeout": httpx.Timeout(30.0),  # Fixed 30 second timeout
                "limits": httpx.Limits(max_keepalive_connections=10, max_connections=20),
                "verify": False,  # Disable SSL verification for internal GitLab
            }
            
            # Auto-detect internal GitLab and disable proxy
            is_internal = self.base_url.startswith("http://10.") or self.base_url.startswith("https://10.")
            if is_internal:
                logger.debug(
                    "Detected internal GitLab, disabling proxy",
                    gitlab_url=self.base_url,
                    is_internal=is_internal,
                )
                
                # Explicitly disable proxy for internal GitLab
                client_kwargs.update({
                    "trust_env": False,  # Don't trust environment proxy settings
                })
                
                logger.debug("Disabled proxy for internal GitLab")
            
            self._session = httpx.AsyncClient(**client_kwargs)
        
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.is_closed:
            await self._session.aclose()

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        retry_count: int = 0,
    ) -> Dict[str, Any]:
        """Make HTTP request with retry logic.
        
        Args:
            method: HTTP method
            endpoint: API endpoint
            params: Query parameters
            json_data: JSON request body
            retry_count: Current retry attempt
            
        Returns:
            JSON response data
            
        Raises:
            GitLabAPIError: When API request fails
        """
        session = await self._ensure_session()
        
        try:
            logger.debug(
                "Making GitLab API request",
                method=method,
                endpoint=endpoint,
                params=params,
                retry_count=retry_count,
            )
            
            response = await session.request(
                method=method,
                url=endpoint,
                params=params,
                json=json_data,
            )
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                raise GitLabAPIError(
                    f"Resource not found: {endpoint}",
                    status_code=response.status_code,
                    response_data=response.json() if response.content else None,
                )
            elif response.status_code == 403:
                raise GitLabAPIError(
                    "Access denied. Check API token permissions.",
                    status_code=response.status_code,
                    response_data=response.json() if response.content else None,
                )
            elif response.status_code == 429:
                # Rate limit exceeded
                if retry_count < self.max_retries:
                    wait_time = 2 ** retry_count
                    logger.warning(
                        "Rate limit exceeded, retrying",
                        wait_time=wait_time,
                        retry_count=retry_count,
                    )
                    await asyncio.sleep(wait_time)
                    return await self._make_request(method, endpoint, params, json_data, retry_count + 1)
                else:
                    raise GitLabAPIError(
                        "Rate limit exceeded. Max retries reached.",
                        status_code=response.status_code,
                    )
            else:
                response.raise_for_status()
                
        except httpx.RequestError as e:
            if retry_count < self.max_retries:
                wait_time = 2 ** retry_count
                logger.warning(
                    "Request failed, retrying",
                    error=str(e),
                    wait_time=wait_time,
                    retry_count=retry_count,
                )
                await asyncio.sleep(wait_time)
                return await self._make_request(method, endpoint, params, json_data, retry_count + 1)
            else:
                raise GitLabAPIError(f"Request failed after {self.max_retries} retries: {e}")
        
        except Exception as e:
            logger.error("Unexpected error during GitLab API request", error=str(e))
            raise GitLabAPIError(f"Unexpected error: {e}")

    async def health_check(self) -> bool:
        """Perform health check on GitLab API.
        
        Returns:
            True if API is accessible, False otherwise
        """
        try:
            await self._make_request("GET", "/user")
            return True
        except Exception:
            return False