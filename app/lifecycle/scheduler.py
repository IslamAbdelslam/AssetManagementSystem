"""APScheduler: marks stale assets on a cron schedule."""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)
settings = get_settings()

_scheduler = AsyncIOScheduler(timezone="UTC")


async def _mark_stale_job() -> None:
    """Runs hourly: marks assets not seen in STALE_THRESHOLD_DAYS as stale."""
    from app.assets.repository import AssetRepository
    from app.database import get_session_factory

    factory = get_session_factory()
    async with factory() as db:
        count = await AssetRepository.mark_all_stale(db, settings.STALE_THRESHOLD_DAYS)
        await db.commit()
        if count:
            log.info("lifecycle.mark_stale.complete", count=count, threshold_days=settings.STALE_THRESHOLD_DAYS)


def start_scheduler() -> None:
    _scheduler.add_job(
        _mark_stale_job,
        trigger=IntervalTrigger(hours=1),
        id="mark_stale",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    _scheduler.start()
    log.info("scheduler.started", jobs=["mark_stale"])


def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")
