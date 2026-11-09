import asyncio
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional, Any

import httpx

# Configure logger for the checker module
logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class CheckResponse:
    """
    Data container representing the raw result of an HTTP check.
    This is passed to the Analyzer for heuristic and statistical processing.
    """
    site_id: int
    url: str
    status_code: Optional[int] = None
    latency_ms: float = 0.0
    headers: Dict[str, str] = field(default_factory=dict)
    content: str = ""
    error_message: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_timeout: bool = False

    @property
    def is_success(self) -> bool:
        """Determines if the transport layer request succeeded, regardless of status code."""
        return self.error_message is None and self.status_code is not None


class WebsiteChecker:
    """
    Handles the execution of asynchronous HTTP requests.
    Designed to capture enough metadata for 'soft failure' detection, including
    response bodies and precise timing.
    """

    def __init__(
        self, 
        user_agent: str = "VigilantAI/1.0 (Monitoring Engine)",
        timeout_seconds: float = 10.0,
        max_redirects: int = 5,
        verify_ssl: bool = True
    ):
        self.timeout = httpx.Timeout(timeout_seconds, connect=5.0)
        self.limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
        self.headers = {"User-Agent": user_agent}
        self.max_redirects = max_redirects
        self.verify_ssl = verify_ssl
        self._lock = asyncio.Lock()
        
        # client is managed externally or initialized on first use if needed
        # but usually, for production, we use a single AsyncClient instance.
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        """Returns a singleton-like AsyncClient for connection pooling."""
        async with self._lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    timeout=self.timeout,
                    limits=self.limits,
                    headers=self.headers,
                    follow_redirects=True,
                    max_redirects=self.max_redirects,
                    verify=self.verify_ssl
                )
            return self._client

    async def close(self):
        """Closes the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _get_latency_ms(self, start_time: float) -> float:
        """Calculates elapsed time in milliseconds."""
        return (time.perf_counter() - start_time) * 1000

    async def check(self, site_id: int, url: str) -> CheckResponse:
        """
        Performs a single HTTP GET request to the target URL.
        Captures latency, status, headers, and body for analysis.
        """
        client = await self.get_client()
        start_time = time.perf_counter()
        
        try:
            async with client.stream('GET', url) as response:
                # Read only the first 512KB to prevent memory exhaustion
                max_bytes = 512 * 1024
                chunks = []
                bytes_received = 0
                
                async for chunk in response.aiter_bytes():
                    chunks.append(chunk)
                    bytes_received += len(chunk)
                    if bytes_received >= max_bytes:
                        break
                
                latency = self._get_latency_ms(start_time)
                content_bytes = b"".join(chunks)[:max_bytes]
                
                # Decode respecting the server's character encoding or fallback to utf-8
                try:
                    encoding = response.encoding or 'utf-8'
                    content_preview = content_bytes.decode(encoding, errors='replace')
                except LookupError:
                    # In case of invalid character sets in headers, fallback to utf-8
                    content_preview = content_bytes.decode('utf-8', errors='replace')

                return CheckResponse(
                    site_id=site_id,
                    url=url,
                    status_code=response.status_code,
                    latency_ms=latency,
                    headers=dict(response.headers),
                    content=content_preview,
                    timestamp=datetime.now(timezone.utc)
                )

        except httpx.ConnectTimeout:
            logger.warning(f"Connection timeout for site {site_id}: {url}")
            return CheckResponse(
                site_id=site_id,
                url=url,
                latency_ms=self._get_latency_ms(start_time),
                error_message="Connection Timeout",
                is_timeout=True
            )
        
        except httpx.ReadTimeout:
            logger.warning(f"Read timeout for site {site_id}: {url}")
            return CheckResponse(
                site_id=site_id,
                url=url,
                latency_ms=self._get_latency_ms(start_time),
                error_message="Read Timeout",
                is_timeout=True
            )

        except httpx.RequestError as exc:
            logger.error(f"Request error for site {site_id} ({url}): {str(exc)}")
            return CheckResponse(
                site_id=site_id,
                url=url,
                latency_ms=self._get_latency_ms(start_time),
                error_message=f"Request Failed: {type(exc).__name__}"
            )
            
        except Exception as exc:
            logger.exception(f"Unexpected error checking site {site_id}")
            return CheckResponse(
                site_id=site_id,
                url=url,
                latency_ms=self._get_latency_ms(start_time),
                error_message=f"Unexpected Error: {str(exc)}"
            )

    async def check_batch(self, sites: list[Dict[str, Any]]) -> list[CheckResponse]:
        """
        Executes a batch of checks concurrently.
        'sites' is expected to be a list of dicts with 'id' and 'url'.
        Throttles concurrent requests to prevent resource exhaustion.
        """
        semaphore = asyncio.Semaphore(50)

        async def throttled_check(site: Dict[str, Any]) -> CheckResponse:
            async with semaphore:
                return await self.check(site['id'], site['url'])

        tasks = [throttled_check(site) for site in sites]
        return await asyncio.gather(*tasks)
