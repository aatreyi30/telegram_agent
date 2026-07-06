"""Scheduler — decides WHEN collection jobs run (spec 08).

Cadences are fully config-driven (no code changes needed to retune, per the
acceptance criteria). Every scheduled tick just enqueues the relevant collector
through the JobRunner, so all runs share the same lifecycle/observability.
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from src.services.collection.base import JobRunner
from src.services.collection.channels import owned_handles
from src.services.collection.merchant import MerchantEnrichmentCollector  # noqa: F401 (registry)
from src.services.collection.telegram_competitor import CompetitorCollector
from src.services.collection.telegram_owned import OwnedChannelCollector
from src.config.settings import get_settings
from src.db.models import CollectionType
from src.logger import get_logger

logger = get_logger(__name__)


class CollectionScheduler:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.runner = JobRunner()
        self.scheduler = BackgroundScheduler(
            job_defaults={"coalesce": True, "max_instances": 1}
        )

    # --- scheduled tick handlers ---
    def _owned_incremental(self) -> None:
        for ch in owned_handles():
            self.runner.run_collector(
                OwnedChannelCollector(ch, CollectionType.INCREMENTAL),
                collection_type=CollectionType.INCREMENTAL,
                target=ch,
            )

    def _owned_analytics(self) -> None:
        for ch in owned_handles():
            self.runner.run_collector(
                OwnedChannelCollector(ch, CollectionType.ANALYTICS),
                collection_type=CollectionType.ANALYTICS,
                target=ch,
            )

    def _competitors(self) -> None:
        for username in self.settings.competitor_channels:
            self.runner.run_collector(
                CompetitorCollector(username, max_pages=1),
                collection_type=CollectionType.INCREMENTAL,
                target=username,
            )

    def start(self) -> None:
        s = self.settings
        if s.owned_channels:
            self.scheduler.add_job(
                self._owned_incremental,
                "interval",
                minutes=s.owned_incremental_interval_min,
                id="owned_incremental",
            )
            self.scheduler.add_job(
                self._owned_analytics,
                "interval",
                minutes=s.owned_analytics_interval_min,
                id="owned_analytics",
            )
            logger.info("scheduled owned-channel collection for %d channel(s)", len(s.owned_channels))
        else:
            logger.warning("no OWNED_CHANNELS configured — owned collection disabled")

        if s.competitor_channels:
            self.scheduler.add_job(
                self._competitors,
                "interval",
                minutes=s.competitor_interval_min,
                id="competitors",
            )
            logger.info("scheduled competitor monitoring for %d channel(s)", len(s.competitor_channels))
        else:
            logger.warning("no COMPETITOR_CHANNELS configured — competitor monitoring disabled")

        self.scheduler.start()
        logger.info("scheduler started")

    def shutdown(self) -> None:
        self.scheduler.shutdown(wait=False)
        logger.info("scheduler stopped")
