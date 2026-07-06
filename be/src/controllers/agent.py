"""The living agent — a scheduled loop that keeps the channel's intelligence and
drafts fresh without manual clicks.

Each cycle (default every 6h, togg[le]able):
  1. collect  — pull new owned posts + competitor posts (best-effort)
  2. discover — search Telegram for similar deal channels, add top matches
  3. analyze  — normalize → classify → merchant/competitor intel → learn → growth
                → reason → plan   (the plan is REBUILT every cycle → never static)
  4. generate — fresh, relevant/attractive drafts from today's live deals (Camoufox)
  5. schedule — auto-queue those drafts into the plan's best posting windows
                (never SENDS — publishing stays gated on channel admin rights)

Every step is best-effort: one failure is logged and the cycle continues. Status,
last/next run, per-step results and a live log are exposed for the UI (/api/agent).
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from src.logger import get_logger

logger = get_logger(__name__)

DEFAULT_INTERVAL_HOURS = 6
_JOB_ID = "agent_cycle"


class AgentScheduler:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sched = BackgroundScheduler(job_defaults={"coalesce": True, "max_instances": 1})
        self._thread: threading.Thread | None = None
        self.enabled = False
        self.interval_hours = DEFAULT_INTERVAL_HOURS
        self.state = "idle"            # idle | running
        self.last_run: str | None = None
        self.next_run: str | None = None
        self.last_summary: str | None = None
        self.steps: list[dict] = []
        self.log: list[str] = []

    # ------------------------------------------------------------------ #
    def status(self) -> dict:
        with self._lock:
            return {
                "enabled": self.enabled, "state": self.state,
                "interval_hours": self.interval_hours,
                "last_run": self.last_run, "next_run": self.next_run,
                "last_summary": self.last_summary,
                "steps": list(self.steps), "log": list(self.log),
            }

    def _emit(self, msg: str) -> None:
        with self._lock:
            self.log.append(msg)
            self.log = self.log[-200:]
        logger.info("[agent] %s", msg)

    def _set_step(self, name: str, status: str, detail: str = "") -> None:
        with self._lock:
            self.steps.append({"name": name, "status": status, "detail": detail})

    # ------------------------------------------------------------------ #
    def start(self, interval_hours: int | None = None, run_now: bool = True) -> dict:
        self.interval_hours = int(interval_hours or self.interval_hours)
        if not self._sched.running:
            self._sched.start()
        self._sched.add_job(self._run_cycle_bg, "interval", hours=self.interval_hours,
                            id=_JOB_ID, replace_existing=True, next_run_time=None)
        self.enabled = True
        self._refresh_next_run()
        self._emit(f"Agent started — cycle every {self.interval_hours}h.")
        if run_now:
            self.run_once()
        return self.status()

    def stop(self) -> dict:
        try:
            self._sched.remove_job(_JOB_ID)
        except Exception:
            pass
        self.enabled = False
        self.next_run = None
        self._emit("Agent stopped.")
        return self.status()

    def run_once(self) -> dict:
        with self._lock:
            if self.state == "running":
                return self.status()
        self._thread = threading.Thread(target=self._run_cycle_bg, daemon=True)
        self._thread.start()
        return self.status()

    def _refresh_next_run(self) -> None:
        try:
            job = self._sched.get_job(_JOB_ID)
            self.next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
        except Exception:
            self.next_run = None

    # ------------------------------------------------------------------ #
    def _run_cycle_bg(self) -> None:
        with self._lock:
            if self.state == "running":
                return
            self.state = "running"
            self.steps = []
            self.log = []
        self._emit("=== Agent cycle started ===")
        started = datetime.now(timezone.utc)
        try:
            self._cycle()
        except Exception as e:  # never let a cycle crash the scheduler thread
            self._emit(f"✗ cycle error: {type(e).__name__}: {e}")
            logger.exception("agent cycle failed")
        finally:
            self.state = "idle"
            self.last_run = started.isoformat()
            self._refresh_next_run()
            done = [s for s in self.steps if s["status"] == "ok"]
            self.last_summary = f"{len(done)}/{len(self.steps)} steps ok"
            self._emit(f"=== Agent cycle finished ({self.last_summary}) ===")

    def _step(self, name: str, fn) -> None:
        """Run one best-effort step, recording status + timing."""
        self._emit(f"→ {name}…")
        try:
            detail = fn() or ""
            self._set_step(name, "ok", str(detail))
            self._emit(f"  ✓ {name} {detail}")
        except Exception as e:
            self._set_step(name, "error", f"{type(e).__name__}: {e}")
            self._emit(f"  • {name} skipped: {type(e).__name__}: {e}")

    def _cycle(self) -> None:
        self._step("collect", self._collect)
        self._step("discover", self._discover)
        self._step("analyze", self._analyze)
        self._step("generate", self._generate)
        self._step("schedule", self._schedule)

    # ---- step implementations (all best-effort) ---- #
    def _collect(self) -> str:
        from src.config.settings import get_settings
        from src.db.models import CollectionType
        from src.services.collection.base import JobRunner
        from src.services.collection.telegram_competitor import CompetitorCollector
        from src.services.collection.telegram_owned import OwnedChannelCollector

        s = get_settings()
        runner = JobRunner()
        added = 0
        for ch in s.owned_channels:
            job = runner.run_collector(OwnedChannelCollector(ch, CollectionType.INCREMENTAL),
                                       collection_type=CollectionType.INCREMENTAL, target=ch)
            added += job.records_added or 0
        for u in s.competitor_channels:
            job = runner.run_collector(CompetitorCollector(u, max_pages=1),
                                       collection_type=CollectionType.INCREMENTAL, target=u)
            added += job.records_added or 0
        return f"(+{added} new posts)"

    def _discover(self) -> str:
        from src.services.collection.discovery import discover_competitors
        result = discover_competitors(max_add=5)
        return f"(+{result.get('added', 0)} channels, {result.get('candidates', 0)} candidates)"

    def _analyze(self) -> str:
        from src.services.classification.classifier import PostClassifier
        from src.db.models import CollectionType
        from src.services.collection.base import JobRunner
        from src.services.intelligence.competitor import CompetitorIntelligenceEngine
        from src.services.intelligence.growth import GrowthEngine
        from src.services.intelligence.merchant import MerchantIntelligenceEngine
        from src.services.intelligence.reasoning import ReasoningEngine
        from src.services.learning.channel_learning import ChannelLearningEngine
        from src.services.planning.campaign import CampaignPlanningEngine
        from src.services.processing.normalizer import PostNormalizer

        runner = JobRunner()
        for name, engine in [("normalize", PostNormalizer()), ("classify", PostClassifier(k=6)),
                             ("merchant-intel", MerchantIntelligenceEngine()),
                             ("competitor-intel", CompetitorIntelligenceEngine()),
                             ("learn", ChannelLearningEngine()), ("growth", GrowthEngine()),
                             ("reason", ReasoningEngine()), ("plan", CampaignPlanningEngine())]:
            runner.run_collector(engine, collection_type=CollectionType.MANUAL, target=name)
        return "(plan refreshed)"

    def _generate(self) -> str:
        from src.db.models import CollectionType
        from src.services.collection.base import JobRunner
        from src.services.generation.deal_source import DealSourceClient
        from src.services.generation.engine import LiveDealGenerationEngine

        client = DealSourceClient()
        ok, _ = client.available()
        if not ok:
            return "(deal source unavailable)"
        raw = [rd.__dict__ for rd in client.fetch_latest(limit=24)]
        if not raw:
            return "(no deals)"
        job = JobRunner().run_collector(LiveDealGenerationEngine(raw, count=6),
                                        collection_type=CollectionType.MANUAL, target="agent_generate")
        return f"(+{job.records_added} drafts)"

    def _schedule(self) -> str:
        from src.config.settings import get_settings
        from src.services.automation.queue import autoschedule
        from src.db.session import session_scope

        s = get_settings()
        channels = s.owned_channels
        if not channels:
            return "(no owned channel to schedule to)"
        with session_scope() as sess:
            report = autoschedule(sess, f"@{channels[0].lstrip('@')}", count=6)
        if not report.get("ok"):
            return f"({report.get('reason', 'nothing to schedule')})"
        return f"(+{len(report.get('scheduled', []))} queued)"


# process-wide singleton
AGENT = AgentScheduler()
