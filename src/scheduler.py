"""Opt-in, non-overlapping automatic scouting and analysis."""
import asyncio
import logging
from . import config

log = logging.getLogger("signalharbor.scheduler")


class PipelineScheduler:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.scheduler = None
        self.task = None
        self.last_result = None
        self.last_error = None
        self.run_lock = asyncio.Lock()

    async def run(self):
        if self.run_lock.locked():
            return {"status": "skipped_running"}
        async with self.run_lock:
            self.task = asyncio.current_task()
            try:
                self.last_result = await self.pipeline()
                self.last_error = None
                return self.last_result
            except asyncio.CancelledError:
                raise
            except Exception:
                self.last_error = "Scheduled pipeline failed; inspect server logs"
                log.exception("Scheduled pipeline failed")
                return {"status": "failed", "error": self.last_error}
            finally:
                self.task = None

    def start(self):
        if not getattr(config, "SCHEDULER_ENABLED", False):
            return
        interval = getattr(config, "SCOUT_INTERVAL_MINUTES", 60)
        if interval <= 0:
            raise ValueError("SCOUT_INTERVAL_MINUTES must be positive")
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self.scheduler.add_job(self.run, "interval", minutes=interval,
                               id="scout-analyze", max_instances=1,
                               coalesce=True, misfire_grace_time=60)
        self.scheduler.start()

    async def stop(self):
        if self.scheduler is not None:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        if self.task is not None and self.task is not asyncio.current_task():
            task = self.task
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def status(self):
        return {"enabled": getattr(config, "SCHEDULER_ENABLED", False),
                "running": self.scheduler is not None,
                "interval_minutes": getattr(config, "SCOUT_INTERVAL_MINUTES", 60),
                "job_running": self.run_lock.locked(),
                "last_result": self.last_result, "last_error": self.last_error}
