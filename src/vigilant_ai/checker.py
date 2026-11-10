import asyncio
import time
import logging
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional, Any

import httpx

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class CheckResponse:
    site_id: Optional[int]
    url: str
    status_code: Optional[int] = None
    latency_ms: float = 0.0
    headers: Dict[str, str] = field(default_factory=dict)
    content: str = ""
    content_hash: str = ""
    error_message: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_timeout: bool = False

    @property
    def is_success(self) -> bool:
        return self.error_message is None and self.status_code is not None

class WebsiteChecker:
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
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
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
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _get_latency_ms(self, start_time: float) -> float:
        return (time.perf_counter() - start_time) * 1000

    async def check(self, url: str, site_id: Optional[int] = None) -> CheckResponse:
        client = await self.get_client()
        start_time = time.perf_counter()
        try:
            async with client.stream('GET', url) as response:
                max_bytes = 512 * 1024
                chunks = []
                bytes_received = 0
                async for chunk in response.aiter_bytes():
                    chunks.append(chunk)
                    bytes_received += len(chunk)
                    if bytes_received >= max_bytes: break
                
                latency = self._get_latency_ms(start_time)
                content_bytes = b"".join(chunks)[:max_bytes]
                content_hash = hashlib.sha256(content_bytes).hexdigest()
                
                try:
                    encoding = response.encoding or 'utf-8'
                    content_preview = content_bytes.decode(encoding, errors='replace')
                except LookupError:
                    content_preview = content_bytes.decode('utf-8', errors='replace')

                return CheckResponse(
                    site_id=site_id, url=url, status_code=response.status_code,
                    latency_ms=latency, headers=dict(response.headers),
                    content=content_preview, content_hash=content_hash,
                    timestamp=datetime.now(timezone.utc)
                )
        except (httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            return CheckResponse(site_id=site_id, url=url, latency_ms=self._get_latency_ms(start_time),
                                 error_message=str(exc), is_timeout=True)
        except Exception as exc:
            return CheckResponse(site_id=site_id, url=url, latency_ms=self._get_latency_ms(start_time),
                                 error_message=str(exc))

    async def check_batch(self, sites: list[Dict[str, Any]]) -> list[CheckResponse]:
        semaphore = asyncio.Semaphore(50)
        async def throttled_check(site: Dict[str, Any]) -> CheckResponse:
            async with semaphore: return await self.check(site['url'], site['id'])
        return await asyncio.gather(*(throttled_check(s) for s in sites))
