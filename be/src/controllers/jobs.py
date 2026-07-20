"""Background job manager for the dashboard.

Runs long actions (the full intelligence pipeline, live-deal generation) in a
worker thread so the HTTP request returns immediately; the page polls /api/job
for a live status + log. Only one job runs at a time (a second request while one
is running is rejected), which matches how the engines expect to be driven.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from src.logger import get_logger

logger = get_logger(__name__)


class _Stopped(Exception):
    """Raised inside a job when the operator requests a stop."""


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.state = "idle"          # idle | running | done | error | stopped
        self.log: list[str] = []
        self.last_briefing: str | None = None
        self.started_at: str | None = None
        self._stop = False

    # ------------------------------------------------------------------ #
    def status(self) -> dict:
        return {"state": self.state, "log": list(self.log),
                "briefing": self.last_briefing, "started_at": self.started_at,
                "stopping": self._stop and self.state == "running"}

    def _emit(self, msg: str) -> None:
        self.log.append(msg)
        logger.info("[dashboard-job] %s", msg)

    def _checkpoint(self) -> None:
        """Cooperative cancellation point — jobs call this between steps."""
        if self._stop:
            raise _Stopped()

    def request_stop(self) -> bool:
        """Ask the running agent to stop at its next checkpoint. False if idle."""
        if self.state != "running":
            return False
        self._stop = True
        self._emit("■ Stop requested — halting after the current step…")
        return True

    def start(self, kind: str, **kwargs) -> bool:
        """Kick off a job. Returns False if one is already running."""
        with self._lock:
            if self.state == "running":
                return False
            self.state = "running"
            self.log = []
            self.last_briefing = None
            self.started_at = datetime.now(timezone.utc).isoformat()
            self._stop = False
        target = {"pipeline": self._run_pipeline,
                  "generate_live": self._run_generate_live}.get(kind)
        if target is None:
            self.state = "error"
            self._emit(f"Unknown job '{kind}'.")
            return True
        self._thread = threading.Thread(target=self._wrap, args=(target, kwargs), daemon=True)
        self._thread.start()
        return True

    def _wrap(self, target, kwargs) -> None:
        try:
            target(**kwargs)
            self.state = "done"
            self._emit("✓ Done.")
        except _Stopped:
            self.state = "stopped"
            self._emit("■ Stopped by operator.")
        except Exception as e:  # never crash the server thread
            self.state = "error"
            self._emit(f"✗ Failed: {type(e).__name__}: {e}")
            logger.exception("dashboard job failed")

    # ------------------------------------------------------------------ #
    def _run_pipeline(self, brief: bool = True) -> None:
        from src.services.classification.classifier import PostClassifier
        from src.services.collection.base import JobRunner
        from src.db.models import CollectionType
        from src.services.intelligence.competitor import CompetitorIntelligenceEngine
        from src.services.intelligence.growth import GrowthEngine
        from src.services.intelligence.merchant import MerchantIntelligenceEngine
        from src.services.intelligence.reasoning import ReasoningEngine
        from src.services.learning.channel_learning import ChannelLearningEngine
        from src.services.planning.campaign import CampaignPlanningEngine
        from src.services.processing.normalizer import PostNormalizer

        runner = JobRunner()
        steps = [
            ("normalize", PostNormalizer()),
            ("classify", PostClassifier(k=6)),
            ("merchant-intel", MerchantIntelligenceEngine()),
            ("competitor-intel", CompetitorIntelligenceEngine()),
            ("learn", ChannelLearningEngine()),
            ("growth", GrowthEngine()),
            ("reason", ReasoningEngine()),
            ("plan", CampaignPlanningEngine()),
        ]
        for name, engine in steps:
            self._checkpoint()   # stop cleanly between steps if requested
            self._emit(f"→ {name}…")
            job = runner.run_collector(engine, collection_type=CollectionType.MANUAL, target=name)
            mark = "✓" if job.status == "completed" else "•"
            extra = f" — {job.error_message}" if job.error_message else ""
            self._emit(f"  {mark} {name}: {job.status} (added={job.records_added}){extra}")

        if brief:
            self._checkpoint()
            self._emit("→ daily plan digest…")
            try:
                from src.controllers.service import digest as _digest
                self.last_briefing = (_digest().get("digest") or None)
                self._emit("  ✓ digest ready" if self.last_briefing
                           else "  • no plan digest yet")
            except Exception as e:  # noqa: BLE001 - best-effort surface of the plan digest
                self._emit(f"  • digest skipped: {e}")

    def _run_generate_live(self, count: int = 5, limit: int = 20) -> None:
        from src.services.collection.base import JobRunner
        from src.db.models import CollectionType
        from src.services.generation.deal_source import DealSourceClient
        from src.services.generation.engine import LiveDealGenerationEngine

        client = DealSourceClient()
        ok, reason = client.available()
        if not ok:
            self._emit(f"  • deal source unavailable: {reason}")
            return
        self._checkpoint()
        self._emit(f"→ fetching today's deals (up to {limit})…")
        raw = [rd.__dict__ for rd in client.fetch_latest(limit=limit)]
        self._emit(f"  fetched {len(raw)} deals")
        if not raw:
            self._emit("  • no deals returned — nothing generated")
            return
        self._emit("→ enrich → rank → format (affiliate links applied)…")
        job = JobRunner().run_collector(
            LiveDealGenerationEngine(raw, count=count),
            collection_type=CollectionType.MANUAL, target="generate_live")
        self._emit(f"  ✓ generated {job.records_added} draft(s) from live deals")


# process-wide singleton
MANAGER = JobManager()
