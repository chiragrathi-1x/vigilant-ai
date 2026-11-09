import asyncio
import logging
import signal
from typing import Dict, List, Optional
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update

from .checker import SiteChecker
from .analyzer import AnomalyAnalyzer
from .notifiers import NotificationManager
from .database import AsyncSessionLocal
from .models import Site, CheckResult

logger = logging.getLogger(__name__)

class MonitoringEngine:
    """
    The core engine responsible for orchestrating the monitoring lifecycle.
    It manages periodic checks, triggers analysis, and dispatches notifications.
    """

    def __init__(self, concurrency_limit: int = 10):
        self.checker = SiteChecker()
        self.analyzer = AnomalyAnalyzer()
        self.notifier = NotificationManager()
        self.concurrency_semaphore = asyncio.Semaphore(concurrency_limit)
        self._running = False
        self._tasks: Dict[int, asyncio.Task] = {}
        self._stop_event = asyncio.Event()

    async def start(self):
        """Starts the monitoring engine daemon."""
        logger.info("Starting Vigilant AI Monitoring Engine...")
        self._running = True
        
        # Setup signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        try:
            while self._running:
                await self._refresh_monitors()
                # Wait for a bit or until stopped before refreshing the site list again
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=60)
                except asyncio.TimeoutError:
                    continue
        except Exception as e:
            logger.error(f"Engine encountered a critical error: {e}", exc_info=True)
        finally:
            await self._cleanup()

    async def stop(self):
        """Stops the engine and cleans up resources."""
        logger.info("Stopping engine...")
        self._running = False
        self._stop_event.set()
        
        for site_id, task in self._tasks.items():
            task.cancel()
        
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        
        logger.info("Engine stopped successfully.")

    async def _refresh_monitors(self):
        """Fetches active sites from DB and ensures a monitoring task exists for each."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Site).where(Site.is_active == True))
            active_sites = result.scalars().all()
            active_ids = {site.id for site in active_sites}

            # Stop tasks for sites no longer in the DB or deactivated
            for site_id in list(self._tasks.keys()):
                if site_id not in active_ids:
                    logger.info(f"Stopping monitor for Site ID {site_id}")
                    task = self._tasks.pop(site_id)
                    task.cancel()

            # Start tasks for new or completed sites
            for site in active_sites:
                # Before starting a new task, ensure existing task reference is handled to avoid overlaps
                if site.id in self._tasks and self._tasks[site.id].done():
                    task = self._tasks.pop(site.id)
                    task.cancel()

                if site.id not in self._tasks:
                    logger.info(f"Starting monitor for {site.url} (Interval: {site.interval_seconds}s)")
                    self._tasks[site.id] = asyncio.create_task(self._monitor_site_loop(site.id))

    async def _monitor_site_loop(self, site_id: int):
        """Infinite loop for a specific site's monitoring schedule."""
        while self._running:
            try:
                interval = None
                # Execute the check with concurrency limiting
                async with self.concurrency_semaphore:
                    interval = await self._perform_check(site_id)
                
                if interval is None:
                    break

                # Wait for the next interval using stop event for immediate interruption
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass

            except asyncio.CancelledError:
                logger.debug(f"Task for site {site_id} cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in monitor loop for site {site_id}: {e}", exc_info=True)
                # Transient error: avoid tight loop by waiting briefly before retry
                await asyncio.sleep(5)

    async def _perform_check(self, site_id: int) -> Optional[int]:
        """Handles the request, analysis, and persistence logic for a single check."""
        async with AsyncSessionLocal() as session:
            site = await session.get(Site, site_id)
            if not site or not site.is_active:
                return None
            
            url = site.url
            interval = site.interval_seconds
            logger.debug(f"Checking {url}...")
            
            # 1. Fetch historical results for anomaly detection
            history_query = (
                select(CheckResult)
                .where(CheckResult.site_id == site_id)
                .order_by(CheckResult.timestamp.desc())
                .limit(20)
            )
            history_res = await session.execute(history_query)
            history = history_res.scalars().all()

            try:
                # 2. Execute HTTP Check
                check_data = await self.checker.check(url)
                
                # 3. Analyze results
                analysis = self.analyzer.analyze(check_data, history)
                
                # 4. Save result to DB
                new_result = CheckResult(
                    site_id=site_id,
                    timestamp=datetime.now(timezone.utc),
                    status_code=check_data.status_code,
                    latency_ms=check_data.latency_ms,
                    content_hash=check_data.content_hash,
                    is_healthy=analysis.is_healthy,
                    failure_reason=analysis.failure_reason,
                    metrics_json=analysis.metrics_meta
                )
                session.add(new_result)

                # 5. Handle Alerts and Recovery
                if not analysis.is_healthy:
                    await self._handle_failure(session, site, url, analysis)
                else:
                    await self._handle_recovery(session, site, url)
            except Exception as e:
                logger.error(f"Network error or check failed for {url}: {e}")
                failure_msg = f"Network Error: {str(e)}"
                # Ensure a CheckResult with is_healthy=False is persisted when unreachable
                new_result = CheckResult(
                    site_id=site_id,
                    timestamp=datetime.now(timezone.utc),
                    status_code=0,
                    latency_ms=0,
                    is_healthy=False,
                    failure_reason=failure_msg,
                    metrics_json={"error": str(e)}
                )
                session.add(new_result)
                
                # Dispatch alert for network reachability failure
                if site.last_status_healthy or site.last_status_healthy is None:
                    site.last_status_healthy = False
                    await self.notifier.send_alert(
                        site_name=site.name or url,
                        url=url,
                        reason=failure_msg,
                        severity="CRITICAL"
                    )

            # 6. Update Site metadata
            site.last_checked_at = datetime.now(timezone.utc)
            
            await session.commit()
            return interval

    async def _handle_failure(self, session: AsyncSession, site: Site, url: str, analysis):
        """Coordinates alert dispatching for detected issues."""
        if site.last_status_healthy or site.last_status_healthy is None:
            logger.warning(f"ALERT: {url} is unhealthy! Reason: {analysis.failure_reason}")
            
            # Update site status
            site.last_status_healthy = False
            
            # Dispatch notification
            await self.notifier.send_alert(
                site_name=site.name or url,
                url=url,
                reason=analysis.failure_reason,
                severity="CRITICAL" if analysis.is_hard_failure else "WARNING"
            )

    async def _handle_recovery(self, session: AsyncSession, site: Site, url: str):
        """Coordinates recovery notifications."""
        if site.last_status_healthy is False:
            logger.info(f"RECOVERY: {url} is back to normal.")
            
            site.last_status_healthy = True
            
            await self.notifier.send_recovery(
                site_name=site.name or url,
                url=url
            )

    async def _cleanup(self):
        """Final cleanup before process exit."""
        if self.checker:
            await self.checker.close()
        logger.info("Cleanup complete.")
