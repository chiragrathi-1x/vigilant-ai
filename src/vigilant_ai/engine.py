import asyncio
import logging
import signal
from typing import Dict, List, Optional
from datetime import datetime, timezone

from sqlalchemy.future import select

from .checker import WebsiteChecker as SiteChecker
from .analyzer import AnomalyAnalyzer
from .notifiers import NotificationManager
from .database import AsyncSessionLocal
from .models import Site, CheckResult

logger = logging.getLogger(__name__)

class MonitoringEngine:
    def __init__(self, concurrency_limit: int = 10):
        self.checker = SiteChecker()
        self.analyzer = AnomalyAnalyzer()
        self.notifier = NotificationManager()
        self.concurrency_semaphore = asyncio.Semaphore(concurrency_limit)
        self._running = False
        self._tasks: Dict[int, asyncio.Task] = {}
        self._stop_event = asyncio.Event()

    async def start(self):
        logger.info("Starting Vigilant AI Monitoring Engine...")
        self._running = True
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))
        try:
            while self._running:
                await self._refresh_monitors()
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=60)
                except asyncio.TimeoutError: continue
        finally: await self._cleanup()

    async def stop(self):
        self._running = False
        self._stop_event.set()
        for task in self._tasks.values(): task.cancel()
        if self._tasks: await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def _refresh_monitors(self):
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Site).where(Site.is_active == True))
            active_sites = result.scalars().all()
            active_ids = {site.id for site in active_sites}
            for site_id in list(self._tasks.keys()):
                if site_id not in active_ids: self._tasks.pop(site_id).cancel()
            for site in active_sites:
                if site.id not in self._tasks or self._tasks[site.id].done():
                    self._tasks[site.id] = asyncio.create_task(self._monitor_site_loop(site.id))

    async def _monitor_site_loop(self, site_id: int):
        while self._running:
            try:
                async with self.concurrency_semaphore:
                    interval = await self._perform_check(site_id)
                if interval is None: break
                try: await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                except asyncio.TimeoutError: pass
            except asyncio.CancelledError: break
            except Exception: await asyncio.sleep(5)

    async def _perform_check(self, site_id: int) -> Optional[int]:
        async with AsyncSessionLocal() as session:
            site = await session.get(Site, site_id)
            if not site or not site.is_active: return None
            
            history_res = await session.execute(select(CheckResult).where(CheckResult.site_id == site_id).order_by(CheckResult.timestamp.desc()).limit(20))
            history = history_res.scalars().all()
            try:
                check_data = await self.checker.check(site.url)
                analysis = self.analyzer.analyze(check_data, history)
                new_result = CheckResult(
                    site_id=site_id, timestamp=datetime.now(timezone.utc),
                    status_code=check_data.status_code or 0,
                    response_time_ms=check_data.latency_ms, content_hash=check_data.content_hash,
                    is_anomaly=not analysis.is_healthy, failure_type=analysis.failure_reason,
                    analysis_details=analysis.metrics_meta
                )
                session.add(new_result)
                if not analysis.is_healthy:
                    await self.notifier.send_alert(site.name, site.url, analysis.failure_reason, "CRITICAL" if analysis.is_hard_failure else "WARNING")
                else:
                    await self.notifier.send_recovery(site.name, site.url)
            except Exception as e:
                session.add(CheckResult(site_id=site_id, status_code=0, response_time_ms=0, is_anomaly=True, failure_type=str(e)))
            
            site.last_checked_at = datetime.now(timezone.utc)
            await session.commit()
            return site.interval_seconds

    async def _cleanup(self):
        if self.checker: await self.checker.close()
