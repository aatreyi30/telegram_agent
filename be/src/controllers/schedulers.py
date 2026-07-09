"""Scheduler registry — the 20 background jobs from the Scheduler Architecture spec.

Each job runs at its specified cadence, is idempotent + retry-safe, and writes a
SchedulerRun log (start/end, records, success/failure, duration, retry, status,
error). Retry policy: 5 → 15 → 30 min, then mark failed + notify.

The whole registry is OFF by default (spec cadences hit live Telegram + the scrape
source constantly). Start/stop it from the Schedulers page; run any job on demand.

Access-limited jobs (reactions/reach, price history, revenue) do whatever is
possible and record status='limited: <reason>' — they never fabricate data.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.logger import get_logger
from src.controllers import cadences as C

logger = get_logger(__name__)
_RETRY_DELAYS_MIN = [5, 15, 30]
# cron times in the spec (06:00, 08:00, …) are IST — the channel is Indian.
IST_TZ = ZoneInfo("Asia/Kolkata")


def _now():
    return datetime.now(timezone.utc)


@dataclass
class Job:
    key: str
    name: str
    cadence: str          # human label
    trigger: object       # APScheduler trigger
    priority: str         # critical | high | medium | low
    fn: Callable[[], dict]


# --------------------------------------------------------------------------- #
# Trigger+label builders — each returns (cadence_label, trigger) together so
# the two can never say different things about when a job runs.
# --------------------------------------------------------------------------- #
def _every_min(n: int):
    return f"every {n} min", IntervalTrigger(minutes=n)


def _every_hr(n: int):
    return f"every {n} h", IntervalTrigger(hours=n)


def _daily(hm: tuple[int, int]):
    h, m = hm
    return f"daily {h:02d}:{m:02d} IST", CronTrigger(hour=h, minute=m)


def _weekly(dow: str, hm: tuple[int, int]):
    h, m = hm
    return f"{dow.capitalize()} {h:02d}:{m:02d} IST", CronTrigger(day_of_week=dow, hour=h, minute=m)


def _monthly(day: int, hm: tuple[int, int]):
    h, m = hm
    suffix = "st" if day == 1 else ("nd" if day == 2 else ("rd" if day == 3 else "th"))
    return f"{day}{suffix} {h:02d}:{m:02d} IST", CronTrigger(day=day, hour=h, minute=m)


# --------------------------------------------------------------------------- #
# Job implementations — each returns {processed, success, failure, detail, status?}
# or raises (→ retry). "limited" jobs set status="limited".
# --------------------------------------------------------------------------- #
def _job_runner():
    from src.services.collection.base import JobRunner
    return JobRunner()


def j_telegram_sync() -> dict:
    from src.db.models import CollectionType
    from src.services.collection.channels import owned_handles
    from src.services.collection.telegram_owned import OwnedChannelCollector
    added = 0
    r = _job_runner()
    for ch in owned_handles():
        job = r.run_collector(OwnedChannelCollector(ch, CollectionType.INCREMENTAL),
                              collection_type=CollectionType.INCREMENTAL, target=ch)
        added += job.records_added or 0
    return {"processed": added, "detail": f"+{added} new owned posts"}


def j_competitor_sync() -> dict:
    from src.config.settings import get_settings
    from src.db.models import CollectionType
    from src.services.collection.telegram_competitor import CompetitorCollector
    added = 0
    r = _job_runner()
    for u in get_settings().competitor_channels:
        job = r.run_collector(CompetitorCollector(u, max_pages=1),
                              collection_type=CollectionType.INCREMENTAL, target=u)
        added += job.records_added or 0
    # also pull tracked (discovered) competitors from the DB
    from sqlalchemy import select
    from src.db.models import Competitor
    from src.db.session import session_scope
    with session_scope() as s:
        extra = [c.username for c in s.scalars(select(Competitor)) if c.username]
    for u in extra:
        if u in get_settings().competitor_channels:
            continue
        try:
            job = r.run_collector(CompetitorCollector(u, max_pages=1),
                                  collection_type=CollectionType.INCREMENTAL, target=u)
            added += job.records_added or 0
        except Exception:
            pass
    return {"processed": added, "detail": f"+{added} competitor posts"}


def j_stats_refresh() -> dict:
    from src.db.models import CollectionType
    from src.services.collection.channels import owned_handles
    from src.services.collection.telegram_owned import OwnedChannelCollector
    r = _job_runner()
    n = 0
    for ch in owned_handles():
        job = r.run_collector(OwnedChannelCollector(ch, CollectionType.ANALYTICS),
                              collection_type=CollectionType.ANALYTICS, target=ch)
        n += job.records_updated or 0
    return {"processed": n, "detail": f"views refreshed (reactions/forwards need admin/bot)"}


def j_link_resolution() -> dict:
    from src.services.collection.link_resolution import LinkResolutionEngine
    n = _run_engine(LinkResolutionEngine(), "link_resolution")
    return {"processed": n, "detail": f"resolved up to {n} shortlinks"}


def _run_engine(engine, target) -> int:
    from src.db.models import CollectionType
    job = _job_runner().run_collector(engine, collection_type=CollectionType.MANUAL, target=target)
    return (job.records_added or 0) + (job.records_updated or 0)


def j_deal_ranking() -> dict:
    return {"processed": 0, "status": "limited",
            "detail": "limited: ranking runs at generation time; live re-score needs stored per-deal metrics"}


def j_price_history() -> dict:
    return {"processed": 0, "status": "limited",
            "detail": "limited: per-product price scraping unavailable for most merchants (blocked/no API)"}


def j_deal_monitoring() -> dict:
    return {"processed": 0, "status": "limited",
            "detail": "limited: per-deal stock/price checks need per-merchant scraping; URL/expiry via url_health"}


def j_growth_detection() -> dict:
    from src.services.intelligence.growth import GrowthEngine
    n = _run_engine(GrowthEngine(), "growth")
    return {"processed": n, "detail": "growth recommendations refreshed"}


def j_competitor_discover() -> dict:
    """Discover new competitor channels. Runs on its own cadence, ahead of sync,
    so newly added competitors get their posts collected by j_competitor_sync
    before j_competitor_intel profiles them (fixes the same-tick ordering bug)."""
    from src.services.collection.discovery import discover_competitors
    added = discover_competitors(max_add=5).get("added", 0)
    return {"processed": added, "detail": f"+{added} competitors discovered"}


def j_competitor_intel() -> dict:
    # profile ONLY over competitors that already have collected posts;
    # discovery runs separately in j_competitor_discover (see above)
    from src.services.intelligence.competitor import CompetitorIntelligenceEngine
    n = _run_engine(CompetitorIntelligenceEngine(), "competitor-intel")
    return {"processed": n, "detail": "competitor intel refreshed"}


def _briefing(weekly=False) -> str:
    from src.ai.briefing import BriefingGenerator
    return BriefingGenerator().generate(weekly=weekly)


def j_ai_daily_summary() -> dict:
    try:
        txt = _briefing(False)
        return {"processed": 1, "detail": (txt or "").split("\n")[0][:80]}
    except Exception as e:
        return {"processed": 0, "status": "limited", "detail": f"limited: AI unavailable ({e})"}


def j_weekly_report() -> dict:
    from src.services.planning.campaign import CampaignPlanningEngine
    _run_engine(CampaignPlanningEngine(), "plan")     # ensure weekly plan is fresh
    try:
        _briefing(True)
        return {"processed": 1, "detail": "weekly plan + AI summary refreshed"}
    except Exception:
        return {"processed": 1, "detail": "weekly plan refreshed (AI summary skipped)"}


def j_monthly_report() -> dict:
    from sqlalchemy import func, select
    from src.db.models import Post
    from src.db.session import session_scope
    with session_scope() as s:
        month_ago = _now() - timedelta(days=30)
        posts = s.scalar(select(func.count()).select_from(Post).where(Post.posted_at >= month_ago)) or 0
    return {"processed": posts, "status": "limited",
            "detail": f"{posts} posts/30d summarized; revenue estimates: limited (no sales data)"}


def j_learning() -> dict:
    from src.services.learning.channel_learning import ChannelLearningEngine
    n = _run_engine(ChannelLearningEngine(), "learn")
    return {"processed": n, "detail": "learning dataset (emoji/CTA/merchant/category) rebuilt"}


def j_queue_processor() -> dict:
    from src.services.automation.scheduler import PostingScheduler
    stats = PostingScheduler().process_due(pacing_seconds=0)
    return {"processed": stats.get("due", 0), "success": stats.get("published", 0),
            "failure": stats.get("failed", 0),
            "detail": f"{stats.get('due',0)} due · {stats.get('blocked',0)} blocked (send gated on admin)"}


def _url_health(limit: int) -> dict:
    import httpx
    from sqlalchemy import select
    from src.db.models_generation import EnrichedDeal
    from src.db.session import session_scope
    with session_scope() as s:
        urls = [d.clean_url or d.url for d in s.scalars(
            select(EnrichedDeal).order_by(EnrichedDeal.id.desc()).limit(limit)) if (d.clean_url or d.url)]
    ok = broken = 0
    with httpx.Client(timeout=8.0, follow_redirects=True) as c:
        for u in urls[:limit]:
            try:
                r = c.head(u)
                if r.status_code < 400 or r.status_code in (403, 405, 429):  # blocked != broken
                    ok += 1
                else:
                    broken += 1
            except Exception:
                broken += 1
    return {"processed": len(urls[:limit]), "success": ok, "failure": broken,
            "detail": f"{ok} ok / {broken} broken of {len(urls[:limit])} checked"}


def j_deal_expiry() -> dict:
    return _url_health(limit=15)


def j_url_health() -> dict:
    return _url_health(limit=40)


def j_normalize_posts() -> dict:
    from src.db.models import CollectionType
    from src.services.processing.normalizer import PostNormalizer
    r = _job_runner()
    job = r.run_collector(PostNormalizer(), collection_type=CollectionType.INCREMENTAL, target="normalize")
    return {"processed": job.records_added or 0, "detail": f"{job.records_added} owned + {job.records_updated} competitor normalized"}


def j_analytics_aggregation() -> dict:
    from src.services.analytics import views as vv
    from src.db.session import session_scope
    with session_scope() as s:
        a = vv.compute(s)
    return {"processed": a.get("total_posts", 0), "detail": f"aggregated {a.get('total_posts',0)} posts"}


def j_merchant_feed_sync() -> dict:
    from src.services.generation.deal_source import DealSourceClient
    from src.services.generation.enrichment import DealEnrichmentEngine, RawDeal
    from src.db.session import session_scope
    client = DealSourceClient()
    ok, reason = client.available()
    if not ok:
        return {"processed": 0, "status": "limited", "detail": f"limited: {reason}"}
    raw = client.fetch_latest(limit=24)
    with session_scope() as s:
        deals = DealEnrichmentEngine(s).enrich_batch([RawDeal(**r.__dict__) if not isinstance(r, RawDeal) else r for r in raw])
        n = len(deals)
    return {"processed": n, "detail": f"+{n} deals enriched/queued"}


def j_notification_engine() -> dict:
    from sqlalchemy import func, select
    from src.db.models_automation import ScheduledPost, ScheduleStatus
    from src.db.models_scheduler import RunStatus, SchedulerRun
    from src.db.session import session_scope
    with session_scope() as s:
        blocked = s.scalar(select(func.count()).select_from(ScheduledPost)
                           .where(ScheduledPost.status == ScheduleStatus.BLOCKED)) or 0
        failed = s.scalar(select(func.count()).select_from(SchedulerRun)
                          .where(SchedulerRun.status == RunStatus.FAILED)) or 0
    alerts = []
    if blocked:
        alerts.append(f"{blocked} posts blocked (need admin rights)")
    if failed:
        alerts.append(f"{failed} scheduler failures")
    return {"processed": len(alerts), "status": "limited" if not alerts else "success",
            "detail": ("; ".join(alerts) if alerts else "no alerts (in-app only; no push channel configured)")}


def j_org_health() -> dict:
    from src.config.settings import get_settings
    from src.services.generation.deal_source import DealSourceClient
    s = get_settings()
    checks = {
        "telegram_creds": bool(s.telegram_api_id and s.telegram_api_hash),
        "affiliate_provider": s.affiliate_provider_name != "generic",
        "deal_source": DealSourceClient().available()[0],
        "ai": s.ai_available,
    }
    healthy = sum(1 for v in checks.values() if v)
    return {"processed": len(checks), "success": healthy, "failure": len(checks) - healthy,
            "detail": " · ".join(f"{k}:{'ok' if v else 'no'}" for k, v in checks.items())}


def j_daily_plan() -> dict:
    from src.services.generation.daily_planner import build_and_schedule_day
    from src.db.session import session_scope
    with session_scope() as s:
        r = build_and_schedule_day(s)
    if not r.get("ok"):
        return {"processed": 0, "status": "limited", "detail": f"limited: {r.get('reason')}"}
    return {"processed": len(r["scheduled"]),
            "detail": f"{len(r['scheduled'])} category posts queued across "
                      f"{len(r['categories'])} categories at proven hours (deduped)"}


def j_daily_report() -> dict:
    """Persist yesterday's DailyChannelReport rows (owned + competitor)."""
    from src.db.session import session_scope
    from src.services.analytics.daily_report import run_daily_reports
    with session_scope() as s:
        return run_daily_reports(s)  # defaults to latest owned date


def j_db_cleanup() -> dict:
    from src.db.models import CollectionEvent
    from src.db.models_scheduler import SchedulerRun
    from src.db.session import session_scope
    cutoff = _now() - timedelta(days=30)
    removed = 0
    with session_scope() as s:
        removed += s.query(SchedulerRun).filter(SchedulerRun.started_at < cutoff).delete()
        removed += s.query(CollectionEvent).filter(CollectionEvent.created_at < cutoff).delete()
    return {"processed": removed, "detail": f"pruned {removed} old log rows (>30d)"}


# --------------------------------------------------------------------------- #
JOBS: list[Job] = [
    Job("telegram_sync", "Telegram Channel Sync", *_every_min(C.TELEGRAM_SYNC_MIN), "critical", j_telegram_sync),
    Job("competitor_sync", "Competitor Channel Sync", *_every_min(C.COMPETITOR_SYNC_MIN), "high", j_competitor_sync),
    Job("normalize_posts", "Post Normalizer", *_every_min(C.NORMALIZE_POSTS_MIN), "high", j_normalize_posts),
    Job("stats_refresh", "Message Statistics Refresh", *_every_min(C.STATS_REFRESH_MIN), "high", j_stats_refresh),
    Job("deal_monitoring", "Deal Monitoring", *_every_hr(C.DEAL_MONITORING_HOURS), "critical", j_deal_monitoring),
    Job("price_history", "Price History Update", *_every_hr(C.PRICE_HISTORY_HOURS), "medium", j_price_history),
    Job("deal_ranking", "Deal Ranking Engine", *_every_min(C.DEAL_RANKING_MIN), "high", j_deal_ranking),
    # Defer reading runtime settings until SchedulerRegistry.start() to avoid
    # calling get_settings() at module import time (startup/circular import issues).
    # Use the default cadence constant here; the real cadence/trigger will be applied at start().
    Job("link_resolution", "Shortlink Resolution", *_every_min(C.LINK_RESOLUTION_DEFAULT_MIN), "high", j_link_resolution),
    Job("growth_detection", "Growth Opportunity Detection", *_daily(C.GROWTH_DETECTION_TIME), "medium", j_growth_detection),
    Job("competitor_discover", "Competitor Discovery", *_daily(C.COMPETITOR_DISCOVER_TIME), "medium", j_competitor_discover),
    Job("competitor_intel", "Competitor Intelligence", *_daily(C.COMPETITOR_INTEL_TIME), "medium", j_competitor_intel),
    Job("ai_daily_summary", "AI Daily Summary", *_daily(C.AI_DAILY_SUMMARY_TIME), "medium", j_ai_daily_summary),
    Job("weekly_report", "Weekly Report", *_weekly(C.WEEKLY_REPORT_DOW, C.WEEKLY_REPORT_TIME), "medium", j_weekly_report),
    Job("monthly_report", "Monthly Report", *_monthly(C.MONTHLY_REPORT_DAY, C.MONTHLY_REPORT_TIME), "medium", j_monthly_report),
    Job("learning", "AI Learning Dataset Builder", *_daily(C.LEARNING_TIME), "medium", j_learning),
    Job("deal_expiry", "Deal Expiry Monitor", *_every_hr(C.DEAL_EXPIRY_HOURS), "high", j_deal_expiry),
    Job("queue_processor", "Scheduler Queue Processor", *_every_min(C.QUEUE_PROCESSOR_MIN), "critical", j_queue_processor),
    Job("url_health", "URL Health Check", *_every_hr(C.URL_HEALTH_HOURS), "low", j_url_health),
    Job("analytics_aggregation", "Analytics Aggregation", *_every_hr(C.ANALYTICS_AGGREGATION_HOURS), "low", j_analytics_aggregation),
    Job("merchant_feed_sync", "Merchant Feed Sync", *_every_min(C.MERCHANT_FEED_SYNC_MIN), "high", j_merchant_feed_sync),
    Job("notification_engine", "Notification Engine", *_every_min(C.NOTIFICATION_ENGINE_MIN), "medium", j_notification_engine),
    Job("org_health", "Organization Health Check", *_every_hr(C.ORG_HEALTH_HOURS), "low", j_org_health),
    Job("db_cleanup", "Database Cleanup", *_daily(C.DB_CLEANUP_TIME), "low", j_db_cleanup),
    Job("daily_report", "Daily Channel Report", *_daily(C.DAILY_REPORT_TIME), "high", j_daily_report),
    Job("daily_plan", "Daily Post Planner", *_daily(C.DAILY_PLAN_TIME), "high", j_daily_plan),
]


def _acquire_singleton_lock():
    """Cross-process exclusive lock so only ONE worker runs the cron (multi-worker
    safe). Returns the held file handle on success, or None if another worker owns it.
    The OS releases the lock automatically if this process dies (no stale locks)."""
    from src.config.settings import get_settings
    s = get_settings()
    s.ensure_dirs()
    path = s.raw_snapshot_dir.parent / "scheduler.lock"
    fh = open(path, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0, os.SEEK_END)
            if fh.tell() == 0:          # msvcrt.locking needs a byte to lock
                fh.write("lock")
                fh.flush()
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


class SchedulerRegistry:
    def __init__(self) -> None:
        self._sched = BackgroundScheduler(timezone=IST_TZ,
                                          job_defaults={"coalesce": True, "max_instances": 1})
        self._by_key = {j.key: j for j in JOBS}
        self._attempts: dict[str, int] = {}
        self.enabled = False
        self._lock = threading.Lock()
        self._singleton_fh = None      # held OS lock while this worker is the leader

    # ---- lifecycle ---- #
    def start_if_leader(self) -> bool:
        """Auto-start path (server boot). Acquires the cross-process lock first, so with
        multiple uvicorn workers only the leader runs the cron; the rest skip cleanly."""
        if self.enabled:
            return True
        fh = _acquire_singleton_lock()
        if fh is None:
            logger.info("[schedulers] another worker holds the scheduler lock — not starting here")
            return False
        self._singleton_fh = fh
        self.start()
        return True

    def start(self) -> dict:
        if not self._sched.running:
            self._sched.start()
        # Apply runtime settings for jobs that depend on configuration. This
        # avoids calling get_settings() at module import time which can cause
        # startup-time NameError / circular import problems.
        try:
            from src.config.settings import get_settings
            s = get_settings()
            for j in JOBS:
                if j.key == "link_resolution":
                    j.cadence = f"every {s.link_resolve_interval_min} min"
                    j.trigger = IntervalTrigger(minutes=s.link_resolve_interval_min)
        except Exception:
            # If settings aren't available, keep the safe default trigger.
            pass
        for j in JOBS:
            self._sched.add_job(self._make(j.key), trigger=j.trigger, id=j.key,
                                replace_existing=True)
        self.enabled = True
        logger.info("[schedulers] started %d jobs", len(JOBS))
        return self.status()

    def stop(self) -> dict:
        for j in JOBS:
            try:
                self._sched.remove_job(j.key)
            except Exception:
                pass
        self.enabled = False
        if self._singleton_fh is not None:      # release the cross-process lock
            try:
                self._singleton_fh.close()
            except Exception:
                pass
            self._singleton_fh = None
        logger.info("[schedulers] stopped")
        return self.status()

    def _make(self, key: str):
        def _fire():
            self.run(key)
        return _fire

    def run(self, key: str) -> None:
        """Execute one job now (used by the scheduler and on-demand), logging + retry."""
        job = self._by_key.get(key)
        if job is None:
            return
        from src.db.models_scheduler import RunStatus, SchedulerRun
        from src.db.session import session_scope
        start = _now()
        attempt = self._attempts.get(key, 0)
        processed = success = failure = 0
        status, detail, error = RunStatus.SUCCESS, None, None
        try:
            res = job.fn() or {}
            processed = int(res.get("processed", 0))
            success = int(res.get("success", 1))
            failure = int(res.get("failure", 0))
            detail = res.get("detail")
            st = res.get("status", RunStatus.SUCCESS)
            status = RunStatus.LIMITED if str(st).startswith("limited") or st == "limited" else st
            self._attempts[key] = 0
        except Exception as e:
            failure, error = 1, f"{type(e).__name__}: {e}"
            if attempt < len(_RETRY_DELAYS_MIN):
                status = RunStatus.RETRYING
                self._attempts[key] = attempt + 1
                delay = _RETRY_DELAYS_MIN[attempt]
                try:
                    self._sched.add_job(self._make(key), "date",
                                        run_date=_now() + timedelta(minutes=delay),
                                        id=f"{key}__retry{attempt}", replace_existing=True)
                except Exception:
                    pass
                logger.warning("[schedulers] %s failed (attempt %d); retry in %dm: %s",
                               key, attempt + 1, delay, error)
            else:
                status = RunStatus.FAILED
                self._attempts[key] = 0
                logger.error("[schedulers] %s FAILED after retries; notifying: %s", key, error)
        end = _now()
        with session_scope() as s:
            s.add(SchedulerRun(scheduler_key=key, started_at=start, ended_at=end,
                               duration_ms=int((end - start).total_seconds() * 1000),
                               records_processed=processed, success_count=success,
                               failure_count=failure, retry_count=attempt,
                               status=status, detail=detail, error=error))

    def run_async(self, key: str) -> None:
        threading.Thread(target=self.run, args=(key,), daemon=True).start()

    # ---- status ---- #
    def status(self) -> dict:
        from sqlalchemy import select
        from src.db.models_scheduler import SchedulerRun
        from src.db.session import session_scope
        last: dict[str, dict] = {}
        with session_scope() as s:
            for j in JOBS:
                r = s.scalar(select(SchedulerRun).where(SchedulerRun.scheduler_key == j.key)
                             .order_by(SchedulerRun.id.desc()))
                if r:
                    last[j.key] = {"status": r.status, "detail": r.detail,
                                   "at": r.started_at.isoformat() if r.started_at else None,
                                   "duration_ms": r.duration_ms}
        jobs = []
        for j in JOBS:
            nxt = None
            try:
                aj = self._sched.get_job(j.key)
                nxt = aj.next_run_time.isoformat() if aj and aj.next_run_time else None
            except Exception:
                pass
            jobs.append({"key": j.key, "name": j.name, "cadence": j.cadence,
                         "priority": j.priority, "next_run": nxt, "last": last.get(j.key)})
        return {"enabled": self.enabled, "count": len(JOBS), "jobs": jobs}

    def recent_logs(self, limit: int = 40) -> list[dict]:
        from sqlalchemy import select
        from src.db.models_scheduler import SchedulerRun
        from src.db.session import session_scope
        with session_scope() as s:
            rows = s.scalars(select(SchedulerRun).order_by(SchedulerRun.id.desc()).limit(limit)).all()
            return [{"key": r.scheduler_key, "status": r.status, "detail": r.detail,
                     "error": r.error, "processed": r.records_processed,
                     "duration_ms": r.duration_ms,
                     "at": r.started_at.isoformat() if r.started_at else None} for r in rows]


REGISTRY = SchedulerRegistry()
