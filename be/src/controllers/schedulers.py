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
    from sqlalchemy import select
    from src.db.models import Competitor
    from src.db.session import session_scope
    added = 0
    r = _job_runner()
    # Only use discovered competitors from database (no env var dependency),
    # and only ones the operator hasn't turned monitoring off for.
    with session_scope() as s:
        usernames = [c.username for c in s.scalars(
            select(Competitor).where(Competitor.monitoring_enabled.is_(True))) if c.username]
    for u in usernames:
        job = r.run_collector(CompetitorCollector(u, max_pages=5),
                              collection_type=CollectionType.INCREMENTAL, target=u)
        added += job.records_added or 0
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


def j_growth_detection() -> dict:
    from src.services.intelligence.growth import GrowthEngine
    n = _run_engine(GrowthEngine(), "growth")
    return {"processed": n, "detail": "growth recommendations refreshed"}


def j_competitor_discover() -> dict:
    """Discover new competitor channels. Runs on its own cadence, ahead of sync,
    so newly added competitors get their posts collected by j_competitor_sync
    before j_competitor_intel profiles them (fixes the same-tick ordering bug)."""
    from src.services.collection.discovery import discover_competitors
    result = discover_competitors(max_add=5)
    if result.get("status") == "disabled":
        return {"processed": 0, "status": "limited",
                "detail": "limited: auto_discover_competitors is off (Settings > Org)"}
    added = result.get("added", 0)
    return {"processed": added, "detail": f"+{added} competitors discovered"}


def j_competitor_intel() -> dict:
    # profile ONLY over competitors that already have collected posts;
    # discovery runs separately in j_competitor_discover (see above)
    from src.services.intelligence.competitor import CompetitorIntelligenceEngine
    n = _run_engine(CompetitorIntelligenceEngine(), "competitor-intel")
    return {"processed": n, "detail": "competitor intel refreshed"}


def j_weekly_report() -> dict:
    from datetime import timedelta
    from src.services.planning.campaign import CampaignPlanningEngine
    from src.db.session import session_scope
    _run_engine(CampaignPlanningEngine(), "plan")     # ensure deterministic weekly plan is fresh

    # Structured AI weekly plan: analyses last week's merchant traction + post-type
    # performance and directs this week's loot:deal ratio + per-day themes. Stored as
    # the most-recent WEEKLY row so the daily planner's this_week_theme lookup picks it.
    ai_note = "AI weekly plan skipped"
    try:
        from src.ai.planner import generate_week_plan
        from src.services.generation.ai_execution import persist_weekly_plan
        from src.services.analytics.periods import ist_today
        with session_scope() as s:
            ws = ist_today() - timedelta(days=ist_today().weekday())
            res = generate_week_plan(s, ws)
            if res.get("available"):
                persist_weekly_plan(s, ws, ws + timedelta(days=6), res["plan"],
                                    digest=res.get("digest", ""), is_ai_generated=True)
                ai_note = f"AI weekly plan: {len(res['plan'].get('daily_themes') or [])} day themes"
    except Exception as e:
        ai_note = f"AI weekly plan skipped ({e})"

    return {"processed": 1, "detail": f"weekly plan refreshed — {ai_note}"}


def j_weekly_retro() -> dict:
    """Phase 2.4 -- builds the WeeklyRetro for the week that just ended (the
    IST Monday->Sunday preceding today), so weekly_report/weekly_brief right
    after it (08:30) can read a fresh retro. Runs every Monday at 07:30 IST --
    30 min before weekly_report -- see cadences.WEEKLY_RETRO_TIME."""
    from src.db.session import session_scope
    from src.services.analytics.periods import to_ist
    from src.services.analytics.retro import build_weekly_retro

    today_ist = to_ist(_now()).date()
    this_monday = today_ist - timedelta(days=today_ist.weekday())
    week_start = this_monday - timedelta(days=7)
    with session_scope() as s:
        row = build_weekly_retro(s, week_start)
        n_adj = len(row.metrics.get("adjustments") or [])
    return {"processed": 1, "detail": f"retro for week of {week_start.isoformat()} — {n_adj} adjustment(s)"}


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
    reclaimed = stats.get("reclaimed", 0)
    detail = f"{stats.get('due',0)} due · {stats.get('blocked',0)} blocked (send gated on admin)"
    if reclaimed:
        detail += f" · reclaimed {reclaimed} stuck 'sending'"
    return {"processed": stats.get("due", 0), "success": stats.get("published", 0),
            "failure": stats.get("failed", 0), "detail": detail}


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


def j_url_health() -> dict:
    return _url_health(limit=40)


def j_normalize_posts() -> dict:
    from src.db.models import CollectionType
    from src.services.processing.normalizer import PostNormalizer
    r = _job_runner()
    job = r.run_collector(PostNormalizer(), collection_type=CollectionType.INCREMENTAL, target="normalize")
    return {"processed": job.records_added or 0, "detail": f"{job.records_added} owned + {job.records_updated} competitor normalized"}


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
        blocked_errors = s.scalars(select(ScheduledPost.last_error)
                                   .where(ScheduledPost.status == ScheduleStatus.BLOCKED)).all()
        failed = s.scalar(select(func.count()).select_from(SchedulerRun)
                          .where(SchedulerRun.status == RunStatus.FAILED)) or 0
    blocked = len(blocked_errors)
    alerts = []
    if blocked:
        # Report the ACTUAL block reason (last_error prefix), not a blanket
        # "need admin rights" — most live blocks were revalidation timeouts, and the
        # old wording sent operators to check permissions that were never the problem.
        from collections import Counter
        reasons = Counter((e or "unknown").split(":")[0].strip() for e in blocked_errors)
        reason_str = ", ".join(f"{n}×{r}" for r, n in reasons.most_common(3))
        alerts.append(f"{blocked} posts blocked ({reason_str})")
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
    """Generate today's AI daily plan (per-post slots: window/type/theme/merchant).
    The slots are filled with fresh inventory just-in-time by `jit_fill` — this job
    only produces the plan, it no longer pre-renders drafts (which went stale)."""
    from src.controllers.service import ensure_daily_ai_plan
    from src.services.analytics.periods import ist_today
    from src.db.session import session_scope
    with session_scope() as s:
        row = ensure_daily_ai_plan(s, ist_today())
        n = len((row.blueprint or {}).get("post_slots") or []) if row else 0
    if row is None:
        return {"processed": 0, "status": "limited",
                "detail": "no AI daily plan (AI unavailable or no owned data yet)"}
    return {"processed": n, "detail": f"AI daily plan ready: {n} slots (filled just-in-time)"}


def j_jit_fill() -> dict:
    """Fill AI-plan slots due within the lookahead with fresh, just-scraped deals."""
    from src.services.generation.jit_fill import fill_due_slots
    from src.db.session import session_scope
    with session_scope() as s:
        r = fill_due_slots(s)
    if not r.get("ok"):
        return {"processed": 0, "status": "limited", "detail": f"limited: {r.get('reason')}"}
    return {"processed": r.get("filled", 0),
            "detail": f"filled {r.get('filled', 0)}/{r.get('due', 0)} due slots fresh"}


def j_daily_report() -> dict:
    """Persist yesterday's DailyChannelReport rows (owned + competitor)."""
    from src.db.session import session_scope
    from src.services.analytics.daily_report import run_daily_reports
    with session_scope() as s:
        return run_daily_reports(s)  # defaults to latest owned date


def j_outcome_collector() -> dict:
    from src.services.analytics.outcomes import collect_due_outcomes
    from src.db.session import session_scope
    with session_scope() as s:
        n = collect_due_outcomes(s)
    return {"processed": n, "detail": f"{n} post outcomes advanced"}


def j_db_cleanup() -> dict:
    from sqlalchemy import func, select
    from src.db.models import CollectionEvent
    from src.db.models_competitor_intel import CompetitorBenchmark, CompetitorProfile
    from src.db.models_scheduler import SchedulerRun
    from src.db.session import session_scope
    cutoff = _now() - timedelta(days=30)
    intel_cutoff = _now() - timedelta(days=90)
    removed = 0
    with session_scope() as s:
        removed += s.query(SchedulerRun).filter(SchedulerRun.started_at < cutoff).delete()
        removed += s.query(CollectionEvent).filter(CollectionEvent.created_at < cutoff).delete()

        # Competitor intel (0.1): keep 90 days of snapshot history, but never drop a
        # competitor's newest snapshot even if it's older than that (so a competitor
        # profiled only once, long ago, doesn't lose its only data point).
        for model in (CompetitorProfile, CompetitorBenchmark):
            latest_per_competitor = dict(s.execute(
                select(model.competitor_id, func.max(model.computed_at))
                .group_by(model.competitor_id)
            ).all())
            stale = s.scalars(select(model).where(model.computed_at < intel_cutoff)).all()
            for row in stale:
                if row.computed_at == latest_per_competitor.get(row.competitor_id):
                    continue
                s.delete(row)
                removed += 1
    return {"processed": removed, "detail": f"pruned {removed} old rows (>30d logs, >90d competitor intel)"}


# --------------------------------------------------------------------------- #
JOBS: list[Job] = [
    Job("telegram_sync", "Telegram Channel Sync", *_every_min(C.TELEGRAM_SYNC_MIN), "critical", j_telegram_sync),
    Job("competitor_sync", "Competitor Channel Sync", *_every_min(C.COMPETITOR_SYNC_MIN), "high", j_competitor_sync),
    Job("normalize_posts", "Post Normalizer", *_every_min(C.NORMALIZE_POSTS_MIN), "high", j_normalize_posts),
    Job("stats_refresh", "Message Statistics Refresh", *_every_min(C.STATS_REFRESH_MIN), "high", j_stats_refresh),
    # Defer reading runtime settings until SchedulerRegistry.start() to avoid
    # calling get_settings() at module import time (startup/circular import issues).
    # Use the default cadence constant here; the real cadence/trigger will be applied at start().
    Job("link_resolution", "Shortlink Resolution", *_every_min(C.LINK_RESOLUTION_DEFAULT_MIN), "high", j_link_resolution),
    Job("growth_detection", "Growth Opportunity Detection", *_daily(C.GROWTH_DETECTION_TIME), "medium", j_growth_detection),
    Job("competitor_discover", "Competitor Discovery", *_daily(C.COMPETITOR_DISCOVER_TIME), "medium", j_competitor_discover),
    Job("competitor_intel", "Competitor Intelligence", *_daily(C.COMPETITOR_INTEL_TIME), "medium", j_competitor_intel),
    Job("weekly_retro", "Weekly Retro", *_weekly("mon", C.WEEKLY_RETRO_TIME), "medium", j_weekly_retro),
    Job("weekly_report", "Weekly Report", *_weekly(C.WEEKLY_REPORT_DOW, C.WEEKLY_REPORT_TIME), "medium", j_weekly_report),
    Job("monthly_report", "Monthly Report", *_monthly(C.MONTHLY_REPORT_DAY, C.MONTHLY_REPORT_TIME), "medium", j_monthly_report),
    Job("learning", "AI Learning Dataset Builder", *_daily(C.LEARNING_TIME), "medium", j_learning),
    Job("queue_processor", "Scheduler Queue Processor", *_every_min(C.QUEUE_PROCESSOR_MIN), "critical", j_queue_processor),
    Job("url_health", "URL Health Check", *_every_hr(C.URL_HEALTH_HOURS), "low", j_url_health),
    Job("merchant_feed_sync", "Merchant Feed Sync", *_every_min(C.MERCHANT_FEED_SYNC_MIN), "high", j_merchant_feed_sync),
    Job("notification_engine", "Notification Engine", *_every_min(C.NOTIFICATION_ENGINE_MIN), "medium", j_notification_engine),
    Job("outcome_collector", "Outcome Collector", *_every_min(C.OUTCOME_COLLECTOR_MIN), "high", j_outcome_collector),
    Job("org_health", "Organization Health Check", *_every_hr(C.ORG_HEALTH_HOURS), "low", j_org_health),
    Job("db_cleanup", "Database Cleanup", *_daily(C.DB_CLEANUP_TIME), "low", j_db_cleanup),
    Job("daily_report", "Daily Channel Report", *_daily(C.DAILY_REPORT_TIME), "high", j_daily_report),
    Job("daily_plan", "Daily Post Planner", *_daily(C.DAILY_PLAN_TIME), "high", j_daily_plan),
    Job("jit_fill", "Just-in-Time Slot Fill", *_every_min(C.QUEUE_PROCESSOR_MIN), "high", j_jit_fill),
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
