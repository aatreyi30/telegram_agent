#!/usr/bin/env python3
"""
collect_data.py

Runs one full daily cycle for the tgagent data-collection engine — the whole
pipeline, not just raw collection:

  1. Collect fresh posts from every OWNED channel (--initial for a historical
     backfill instead of the default incremental sync).
  2. Discover new competitor channels on Telegram (MTProto search).
  3. Collect fresh posts from every COMPETITOR channel (existing + newly discovered).
  4. Normalize raw posts -> structured NormalizedPost rows (prices, coupons,
     links, merchant detection).
  5. Resolve shortlinks (grbn.in etc.) to their real merchant.
  6. Classify posts into learned post-type clusters.
  7. Build merchant intelligence (profiles, metric windows, opportunities).
  8. Build competitor intelligence (profiles, benchmarks vs us).
  9. Backfill DailyChannelReport rows for every day in the export window.
 10. Optionally (--backtest) run a historical baseline_v1 self-eval over the
     window's owned posts, so prediction accuracy is visible on the weekly
     retro / /plan immediately (see services/analytics/backtest.py).
 11. Pull everything for "yesterday" + "today" (or one exact --date) out of
     the main operational database and mirror it into a SEPARATE, freshly
     generated .db file — channels, competitors, posts, competitor posts,
     normalized posts, extracted prices/coupons/links, classifications,
     merchants + products, merchant/competitor intelligence, the Predict ->
     Outcome -> Retro loop tables, deal scores, AI outputs, daily reports,
     campaign plans, and the subscriber/velocity growth tables.

Run from the project root (the folder that contains the `src/` package),
using the same Python environment the app normally runs in:

    python scripts/collect_data.py --date yesterday

Common flags:

    --date yesterday | today | 2026-07-08     # export exactly one calendar day
    --days-back 1                              # or a range: yesterday+today (default)
    --export-db-url sqlite:///./data/x.db      # omit to auto-name by date
    --initial                                  # owned collection = historical backfill
    --pages 3                                  # t.me/s pages per competitor
    --max-new-competitors 5                    # discovery cap
    --link-resolve-limit 300                   # shortlinks resolved per run
    --link-resolve-concurrency 10              # CONSERVATIVE vs the live scheduler's default
    --http-timeout 15                          # explicit timeout for scripted network calls
    --pace-seconds 2.0                         # sleep between targets — never hammer Telegram
    --classify-k 6                             # post-type clusters to learn
    --backtest                                 # historical baseline_v1 self-eval (off by default)
    --backtest-batch-size 200                  # commit chunk size for --backtest
    --skip-owned / --skip-discovery / --skip-competitors
    --skip-normalize / --skip-link-resolution / --skip-classify
    --skip-merchant-intel / --skip-competitor-intel
    --export-only                              # skip EVERYTHING above, just
                                                # generate the .db from what's
                                                # already in tgagent.db
    --dry-run                                  # print what would happen, do nothing

Environment:
    DB_URL          - the MAIN/operational database (tgagent.db). Left untouched.
    EXPORT_DB_URL    - overrides the auto-generated destination filename if set.

Exit code is non-zero if any stage raised an unhandled error, so this is safe
to wire into cron / systemd-timer / Airflow with normal alerting.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Make sure "src" is importable when this script is run as
# `python scripts/collect_data.py` from the project root.
# --------------------------------------------------------------------------- #
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Collect yesterday+today's data and mirror it into a separate export DB, "
                    "discovering + collecting competitors along the way.",
    )
    p.add_argument(
        "--export-db-url",
        default=os.environ.get("EXPORT_DB_URL"),
        help="SQLAlchemy URL for the generated snapshot DB. If omitted, a file is "
             "auto-named by the date being exported, e.g. ./data/daily_export_2026-07-08.db "
             "(or ./data/daily_export_2026-07-08_to_2026-07-09.db for a range).",
    )
    p.add_argument("--days-back", type=int, default=1,
                    help="How many days before today to include. 1 = yesterday+today (default). "
                         "Ignored if --date is set.")
    p.add_argument("--date", default=None,
                    help="Export exactly ONE calendar day (UTC), e.g. --date 2026-07-08 for "
                         "yesterday, or --date today / --date yesterday. Overrides --days-back.")
    p.add_argument("--initial", action="store_true",
                    help="Owned-channel collection uses CollectionType.INITIAL (historical backfill) "
                         "instead of the default CollectionType.INCREMENTAL.")
    p.add_argument("--pages", type=int, default=3,
                    help="t.me/s pages to paginate per competitor collection run (default 3).")
    p.add_argument("--max-new-competitors", type=int, default=5,
                    help="Cap on new competitors added per discovery run (default 5).")
    p.add_argument("--skip-owned", action="store_true", help="Skip owned-channel collection.")
    p.add_argument("--skip-discovery", action="store_true", help="Skip competitor discovery.")
    p.add_argument("--skip-competitors", action="store_true", help="Skip competitor collection.")
    p.add_argument("--skip-normalize", action="store_true",
                    help="Skip Phase 2 normalization (normalized posts, prices, coupons, links).")
    p.add_argument("--skip-link-resolution", action="store_true",
                    help="Skip resolving shortlinks to their real merchant (grbn.in etc).")
    p.add_argument("--skip-classify", action="store_true",
                    help="Skip Phase 3 post-type clustering/classification.")
    p.add_argument("--skip-merchant-intel", action="store_true",
                    help="Skip Phase 4 merchant intelligence (profiles/opportunities).")
    p.add_argument("--skip-competitor-intel", action="store_true",
                    help="Skip Phase 5 competitor intelligence (profiles/benchmarks).")
    p.add_argument("--link-resolve-limit", type=int, default=300,
                    help="Max shortlinks to resolve this run (default 300).")
    p.add_argument("--link-resolve-concurrency", type=int, default=10,
                    help="Concurrent shortlink resolutions in flight (default 10). Deliberately "
                         "CONSERVATIVE vs the live scheduler's LINK_RESOLVE_CONCURRENCY default "
                         "(200) — this script may run unattended against production Telegram/"
                         "merchant sites, so it never inherits the engine's high-throughput default.")
    p.add_argument("--http-timeout", type=float, default=15.0,
                    help="Explicit timeout in seconds for network calls this script configures "
                         "directly (currently: link resolution's httpx client). Default 15.0 — "
                         "no call this script makes may hang forever.")
    p.add_argument("--pace-seconds", type=float, default=2.0,
                    help="Seconds to sleep between each owned channel, each competitor, and "
                         "around discovery (default 2.0). Collection stays sequential; this just "
                         "adds breathing room so a run never hammers Telegram/t.me/s back-to-back. "
                         "Telethon FloodWait is handled by the collector/JobRunner itself (capped "
                         "exponential backoff) — this is a separate, additional courtesy delay.")
    p.add_argument("--classify-k", type=int, default=6,
                    help="Number of post-type clusters to learn (default 6).")
    p.add_argument("--backtest", action="store_true",
                    help="After collection+normalization+intel, run a historical baseline_v1 "
                         "self-eval over owned posts in the export window: writes PostPrediction "
                         "(model_version='baseline_v1_backtest') + PostOutcome rows and builds any "
                         "IST WeeklyRetro the window touches, so prediction accuracy shows up on "
                         "/plan + the retro without waiting for the live pipeline. OFF by default. "
                         "See services/analytics/backtest.py for the no-look-ahead guarantee.")
    p.add_argument("--backtest-batch-size", type=int, default=200,
                    help="Posts per commit chunk during --backtest (default 200) — keeps the "
                         "backtest from building one giant transaction or loading the whole posts "
                         "table into memory.")
    p.add_argument("--export-only", action="store_true",
                    help="Skip ALL collection/discovery/normalization/intel stages, just export "
                         "whatever is already in the database (daily-report backfill + --backtest, "
                         "if requested, still run — both are read-mostly/idempotent).")
    p.add_argument("--dry-run", action="store_true",
                    help="Log what would run without touching any database.")
    p.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    return p.parse_args()


ARGS = _parse_args()

logging.basicConfig(
    level=getattr(logging, ARGS.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("collect_data")

if ARGS.export_only:
    ARGS.skip_owned = ARGS.skip_discovery = ARGS.skip_competitors = True
    ARGS.skip_normalize = ARGS.skip_link_resolution = ARGS.skip_classify = True
    ARGS.skip_merchant_intel = ARGS.skip_competitor_intel = True


def _auto_export_db_url(days_back: int, single_date: str | None) -> str:
    """Build a fresh, date-stamped sqlite filename, e.g.
    ./data/daily_export_2026-07-08.db (single day) or
    ./data/daily_export_2026-07-08_to_2026-07-09.db (a range)."""
    now = datetime.now(timezone.utc)
    today = now.date()

    if single_date:
        key = single_date.strip().lower()
        if key == "today":
            day = today
        elif key == "yesterday":
            day = today - timedelta(days=1)
        else:
            day = datetime.strptime(single_date.strip(), "%Y-%m-%d").date()
        return f"sqlite:///./data/daily_export_{day.isoformat()}.db"

    start_day = today - timedelta(days=days_back)
    return f"sqlite:///./data/daily_export_{start_day.isoformat()}_to_{today.isoformat()}.db"


if not ARGS.export_db_url:
    ARGS.export_db_url = _auto_export_db_url(ARGS.days_back, ARGS.date)

# --------------------------------------------------------------------------- #
# NOTE: src.config.settings.get_settings() is @lru_cache'd, so DB_URL must
# already be correct in the environment (e.g. via .env / your normal deploy
# config) *before* we import anything from `src`. This script never rewrites
# DB_URL — it only ever reads FROM that DB and writes TO --export-db-url.
# --------------------------------------------------------------------------- #
from sqlalchemy import create_engine, select, or_, and_
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.config.settings import get_settings
from src.db.base import Base
from src.db.session import init_db, session_scope
from src.db.models import (
    AffiliateLink,
    Channel,
    Competitor,
    CompetitorPost,
    Merchant,
    MerchantProduct,
    Post,
    PostMetricSnapshot,
    ProductPriceSnapshot,
)
from src.db.models_normalization import (
    DiscoveredDomain,
    ExtractedCoupon,
    ExtractedLink,
    ExtractedPrice,
    NormalizedPost,
    SourceType,
)
from src.db.models_classification import PostClassification, PostTypeCluster
from src.db.models_intelligence import MerchantMetricWindow, MerchantOpportunity, MerchantProfile
from src.db.models_competitor_intel import CompetitorBenchmark, CompetitorProfile
from src.db.models_prediction import PostOutcome, PostPrediction, WeeklyRetro
from src.db.models_deal_score import DealScore
from src.db.models_ai_output import AIOutput
from src.db.models_report import DailyChannelReport
from src.db.models_campaign import CampaignPlan
from src.db.models_growth_snapshot import DailySubscriberStat, ParticipantSnapshot
from src.services.collection.base import JobRunner
from src.services.collection.channels import owned_handles
from src.services.collection.telegram_owned import OwnedChannelCollector
from src.services.collection.telegram_competitor import CompetitorCollector
from src.db.models import CollectionType


# ============================================================================
# 1. COLLECTION — owned channels, competitor discovery, competitor channels
# ============================================================================

@dataclass
class RunSummary:
    owned_jobs: list = field(default_factory=list)
    discovery: dict | None = None
    competitor_jobs: list = field(default_factory=list)
    normalize_job: dict | None = None
    link_resolution_job: dict | None = None
    classify_job: dict | None = None
    merchant_intel_job: dict | None = None
    competitor_intel_job: dict | None = None
    daily_report_job: dict | None = None
    backtest_job: dict | None = None
    errors: list = field(default_factory=list)


def collect_owned(summary: RunSummary, pace_seconds: float, initial: bool) -> None:
    handles = owned_handles()
    if not handles:
        log.warning("No owned channels configured (channels table empty and OWNED_CHANNELS unset). Skipping.")
        return
    collection_type = CollectionType.INITIAL if initial else CollectionType.INCREMENTAL
    log.info("Collecting %d owned channel(s) [%s]: %s", len(handles), collection_type, ", ".join(handles))
    runner = JobRunner()
    for i, handle in enumerate(handles):
        try:
            job = runner.run_collector(
                OwnedChannelCollector(handle, collection_type),
                collection_type=collection_type,
                target=handle,
            )
            log.info(
                "  owned:%s -> %s (added=%s updated=%s processed=%s)",
                handle, job.status, job.records_added, job.records_updated, job.records_processed,
            )
            summary.owned_jobs.append({"channel": handle, "status": job.status,
                                        "added": job.records_added})
        except Exception as exc:  # noqa: BLE001
            log.error("  owned:%s FAILED: %s", handle, exc)
            summary.errors.append(f"owned:{handle}: {exc}")
        # pace between targets (Task C.1) — never hammer Telegram back-to-back
        if pace_seconds > 0 and i < len(handles) - 1:
            time.sleep(pace_seconds)


def discover_new_competitors(summary: RunSummary, max_add: int, pace_seconds: float) -> None:
    settings = get_settings()
    if not (settings.telegram_api_id and settings.telegram_api_hash):
        log.warning(
            "TELEGRAM_API_ID/TELEGRAM_API_HASH not set — competitor discovery needs MTProto "
            "search and cannot run. Skipping discovery (existing competitors will still be collected)."
        )
        return
    from src.services.collection.discovery import discover_competitors

    log.info("Discovering up to %d new competitor channel(s)...", max_add)
    try:
        result = discover_competitors(max_add=max_add)
        summary.discovery = result
        log.info(
            "  discovery: %d candidate(s) scanned, %d new competitor(s) added: %s",
            result.get("candidates", 0), result.get("added", 0), result.get("top", []),
        )
    except Exception as exc:  # noqa: BLE001
        log.error("  discovery FAILED: %s", exc)
        summary.errors.append(f"discovery: {exc}")
    # pace AROUND discovery (Task C.1) — a beat before competitor collection starts
    if pace_seconds > 0:
        time.sleep(pace_seconds)


def collect_competitors(summary: RunSummary, pages: int, pace_seconds: float) -> None:
    with session_scope() as s:
        usernames = list(
            s.scalars(select(Competitor.username).where(
                Competitor.username.isnot(None), Competitor.monitoring_enabled.is_(True)))
        )
    if not usernames:
        log.warning("No competitors on file yet (table empty, discovery off/unavailable, "
                    "or all competitors have monitoring turned off). Skipping.")
        return
    log.info("Collecting %d competitor channel(s), %d page(s) each...", len(usernames), pages)
    runner = JobRunner()
    for i, username in enumerate(usernames):
        try:
            job = runner.run_collector(
                CompetitorCollector(username, max_pages=pages),
                collection_type=CollectionType.INCREMENTAL,
                target=username,
            )
            log.info(
                "  competitor:%s -> %s (added=%s updated=%s processed=%s)",
                username, job.status, job.records_added, job.records_updated, job.records_processed,
            )
            summary.competitor_jobs.append({"competitor": username, "status": job.status,
                                             "added": job.records_added})
        except Exception as exc:  # noqa: BLE001
            log.error("  competitor:%s FAILED: %s", username, exc)
            summary.errors.append(f"competitor:{username}: {exc}")
        # pace between targets (Task C.1)
        if pace_seconds > 0 and i < len(usernames) - 1:
            time.sleep(pace_seconds)


def run_normalize(summary: RunSummary) -> None:
    """Phase 2: turn raw posts into NormalizedPost + extracted prices/coupons/links."""
    from src.services.processing.normalizer import PostNormalizer

    log.info("Normalizing raw posts (owned + competitor)...")
    try:
        job = JobRunner().run_collector(
            PostNormalizer(include_owned=True, include_competitor=True),
            collection_type=CollectionType.MANUAL,
            target="normalize",
        )
        log.info("  normalize -> %s (added=%s updated=%s processed=%s)",
                  job.status, job.records_added, job.records_updated, job.records_processed)
        summary.normalize_job = {"status": job.status, "added": job.records_added}
    except Exception as exc:  # noqa: BLE001
        log.error("  normalize FAILED: %s", exc)
        summary.errors.append(f"normalize: {exc}")


def run_link_resolution(summary: RunSummary, limit: int, concurrency: int, timeout: float) -> None:
    """Follow grbn.in/short links to their real merchant (fills ExtractedLink.merchant_key).

    Task C.4 — `concurrency`/`timeout` are passed straight into
    `LinkResolutionEngine` rather than relying on the live scheduler's
    `settings.link_resolve_concurrency` (200) default, since this script may
    run unattended against production Telegram/merchant sites."""
    from src.services.collection.link_resolution import LinkResolutionEngine

    log.info("Resolving up to %d shortlink(s) (concurrency=%d, timeout=%.1fs)...",
              limit, concurrency, timeout)
    try:
        job = JobRunner().run_collector(
            LinkResolutionEngine(limit=limit, delay=0.3, concurrency=concurrency, timeout=timeout),
            collection_type=CollectionType.MANUAL,
            target="link_resolution",
        )
        log.info("  link_resolution -> %s (added=%s updated=%s processed=%s)",
                  job.status, job.records_added, job.records_updated, job.records_processed)
        summary.link_resolution_job = {"status": job.status, "updated": job.records_updated}
    except Exception as exc:  # noqa: BLE001
        log.error("  link_resolution FAILED: %s", exc)
        summary.errors.append(f"link_resolution: {exc}")


def run_classify(summary: RunSummary, k: int, seed: int = 42) -> None:
    """Phase 3: learn post-type clusters + assign every normalized post to one."""
    from src.services.classification.classifier import PostClassifier

    log.info("Classifying post types (k=%d)...", k)
    try:
        job = JobRunner().run_collector(
            PostClassifier(k=k, seed=seed),
            collection_type=CollectionType.MANUAL,
            target=f"classify(k={k})",
        )
        log.info("  classify -> %s (added=%s updated=%s processed=%s)",
                  job.status, job.records_added, job.records_updated, job.records_processed)
        summary.classify_job = {"status": job.status, "added": job.records_added}
    except Exception as exc:  # noqa: BLE001
        log.error("  classify FAILED: %s", exc)
        summary.errors.append(f"classify: {exc}")


def run_merchant_intel(summary: RunSummary) -> None:
    """Phase 4: build merchant profiles, metric windows, and opportunities."""
    from src.services.intelligence.merchant import MerchantIntelligenceEngine

    log.info("Building merchant intelligence...")
    try:
        job = JobRunner().run_collector(
            MerchantIntelligenceEngine(),
            collection_type=CollectionType.MANUAL,
            target="merchant_intel",
        )
        log.info("  merchant_intel -> %s (added=%s updated=%s processed=%s)",
                  job.status, job.records_added, job.records_updated, job.records_processed)
        summary.merchant_intel_job = {"status": job.status, "added": job.records_added}
    except Exception as exc:  # noqa: BLE001
        log.error("  merchant_intel FAILED: %s", exc)
        summary.errors.append(f"merchant_intel: {exc}")


def run_competitor_intel(summary: RunSummary) -> None:
    """Phase 5: build competitor profiles and benchmarks vs us."""
    from src.services.intelligence.competitor import CompetitorIntelligenceEngine

    log.info("Building competitor intelligence...")
    try:
        job = JobRunner().run_collector(
            CompetitorIntelligenceEngine(),
            collection_type=CollectionType.MANUAL,
            target="competitor_intel",
        )
        log.info("  competitor_intel -> %s (added=%s updated=%s processed=%s)",
                  job.status, job.records_added, job.records_updated, job.records_processed)
        summary.competitor_intel_job = {"status": job.status, "added": job.records_added}
    except Exception as exc:  # noqa: BLE001
        log.error("  competitor_intel FAILED: %s", exc)
        summary.errors.append(f"competitor_intel: {exc}")


def run_daily_reports_for_window(summary: RunSummary, start: datetime, end: datetime) -> None:
    """Task A.3 — backfill DailyChannelReport rows for every day the export
    window covers, so the AI/plan/report surfaces have owned-channel daily
    aggregates for dates that predate this script's own run.

    Idempotent: `build_owned_report` + `persist_report` upsert on
    (channel_id, report_date, source_type), so reruns for the same window are
    safe. Runs unconditionally (not gated by any --skip-* flag) — it's a
    read-mostly aggregation over whatever is already in the database, which is
    exactly what --export-only wants filled in too."""
    from src.services.analytics.daily_report import build_owned_report, persist_report

    days: list[date] = []
    d = start.date()
    end_date = end.date()  # `end` is the exclusive next-day boundary
    while d < end_date:
        days.append(d)
        d += timedelta(days=1)
    if not days:
        return

    log.info("Building daily channel reports for %d day(s): %s -> %s",
              len(days), days[0].isoformat(), days[-1].isoformat())
    try:
        built = 0
        with session_scope() as s:
            for day in days:
                persist_report(s, build_owned_report(s, day))
                built += 1
        log.info("  daily_report -> upserted %d day(s)", built)
        summary.daily_report_job = {"days": built}
    except Exception as exc:  # noqa: BLE001
        log.error("  daily_report FAILED: %s", exc)
        summary.errors.append(f"daily_report: {exc}")


def run_backtest_step(summary: RunSummary, start: datetime, end: datetime, batch_size: int) -> None:
    """Task B — historical baseline_v1 self-eval over the export window's
    owned posts. OFF unless --backtest is passed. See
    services/analytics/backtest.py for the no-look-ahead guarantee and
    batching (Task C.5)."""
    from src.services.analytics.backtest import run_backtest

    log.info("Running baseline_v1 backtest over %s -> %s (batch_size=%d)...",
              start.isoformat(), end.isoformat(), batch_size)
    try:
        with session_scope() as s:
            counts = run_backtest(s, start, end, batch_size=batch_size)
        log.info("  backtest -> %s", counts)
        summary.backtest_job = counts
    except Exception as exc:  # noqa: BLE001
        log.error("  backtest FAILED: %s", exc)
        summary.errors.append(f"backtest: {exc}")


# ============================================================================
# 2. EXPORT — mirror yesterday+today into a separate database
# ============================================================================

# Tables to mirror. Reuses the *same* SQLAlchemy Table objects the main app
# defines (Base.metadata) so the export DB's schema always matches the source
# schema exactly — we just point create_all() at a different engine.
EXPORT_TABLES = [
    # raw collected data
    Channel.__table__, Competitor.__table__, Post.__table__, CompetitorPost.__table__,
    # Phase 2: normalization
    NormalizedPost.__table__, ExtractedPrice.__table__, ExtractedCoupon.__table__,
    ExtractedLink.__table__, DiscoveredDomain.__table__,
    # Phase 3: classification
    PostTypeCluster.__table__, PostClassification.__table__,
    # merchant registry + pricing
    Merchant.__table__, MerchantProduct.__table__, ProductPriceSnapshot.__table__,
    AffiliateLink.__table__,
    # Phase 4: merchant intelligence
    MerchantProfile.__table__, MerchantMetricWindow.__table__, MerchantOpportunity.__table__,
    # Phase 5: competitor intelligence
    CompetitorProfile.__table__, CompetitorBenchmark.__table__,
    # upgrade.md Phase 2: predict -> outcome -> retro loop
    PostPrediction.__table__, PostOutcome.__table__, WeeklyRetro.__table__,
    # upgrade.md Phase 3: deal scoring history
    DealScore.__table__,
    # upgrade.md Phase 0.2: persisted AI outputs
    AIOutput.__table__,
    # daily aggregate report rows
    DailyChannelReport.__table__,
    # Phase 10: campaign plans
    CampaignPlan.__table__,
    # velocity / growth data
    PostMetricSnapshot.__table__, DailySubscriberStat.__table__, ParticipantSnapshot.__table__,
]


def _window(days_back: int, single_date: str | None = None) -> tuple[datetime, datetime]:
    """UTC [start, end) window.

    - If `single_date` is given ("YYYY-MM-DD", "today", or "yesterday"), the
      window is exactly that ONE calendar day.
    - Otherwise it covers `days_back` day(s) ago through the end of today
      (days_back=1 -> yesterday+today, days_back=0 -> today only).
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if single_date:
        key = single_date.strip().lower()
        if key == "today":
            day_start = today_start
        elif key == "yesterday":
            day_start = today_start - timedelta(days=1)
        else:
            day_start = datetime.strptime(single_date.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return day_start, day_start + timedelta(days=1)

    start = today_start - timedelta(days=days_back)
    end = today_start + timedelta(days=1)  # exclusive upper bound = start of tomorrow
    return start, end


def _get_export_engine(url: str) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    if url.startswith("sqlite:///"):
        db_path = url.split("///", 1)[-1]
        parent = Path(db_path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, echo=False, future=True, connect_args=connect_args)
    Base.metadata.create_all(engine, tables=EXPORT_TABLES)
    return engine


def _row_to_dict(obj) -> dict:
    table = obj.__table__
    return {c.name: getattr(obj, c.name) for c in table.columns}


def _upsert(dest_engine: Engine, table, rows: list[dict]) -> int:
    """Insert rows into `table` on dest_engine, replacing any existing row with
    the same primary key. Works for SQLite and Postgres destinations; falls
    back to delete-then-insert for anything else."""
    if not rows:
        return 0
    dialect = dest_engine.dialect.name
    pk_cols = [c.name for c in table.primary_key.columns]

    with dest_engine.begin() as conn:
        if dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            stmt = sqlite_insert(table)
            update_cols = {c.name: stmt.excluded[c.name] for c in table.columns if c.name not in pk_cols}
            stmt = stmt.on_conflict_do_update(index_elements=pk_cols, set_=update_cols)
            conn.execute(stmt, rows)
        elif dialect in ("postgresql", "postgres"):
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            stmt = pg_insert(table)
            update_cols = {c.name: stmt.excluded[c.name] for c in table.columns if c.name not in pk_cols}
            stmt = stmt.on_conflict_do_update(index_elements=pk_cols, set_=update_cols)
            conn.execute(stmt, rows)
        else:
            # generic fallback: delete matching PKs, then plain insert
            for row in rows:
                cond = [table.c[k] == row[k] for k in pk_cols]
                conn.execute(table.delete().where(*cond))
            conn.execute(table.insert(), rows)
    return len(rows)


def export_window(export_db_url: str, start: datetime, end: datetime) -> dict:
    log.info("Exporting window %s -> %s (UTC) into %s", start.isoformat(), end.isoformat(), export_db_url)

    dest_engine = _get_export_engine(export_db_url)
    counts: dict[str, int] = {}

    with session_scope() as s:  # source (main) DB, read-only here
        # --- raw collected data, scoped to the window ------------------------
        posts = list(
            s.scalars(
                select(Post).where(
                    or_(
                        Post.posted_at.between(start, end),
                        Post.posted_at.is_(None) & Post.collected_at.between(start, end),
                    )
                )
            )
        )
        competitor_posts = list(
            s.scalars(
                select(CompetitorPost).where(
                    or_(
                        CompetitorPost.posted_at.between(start, end),
                        CompetitorPost.posted_at.is_(None) & CompetitorPost.collected_at.between(start, end),
                    )
                )
            )
        )
        owned_post_ids = [p.id for p in posts]
        competitor_post_ids = [p.id for p in competitor_posts]

        # --- Phase 2: normalization, scoped to those same posts --------------
        normalized_posts: list = []
        if owned_post_ids:
            normalized_posts += list(s.scalars(
                select(NormalizedPost).where(
                    and_(NormalizedPost.source_type == SourceType.OWNED,
                         NormalizedPost.source_id.in_(owned_post_ids))
                )
            ))
        if competitor_post_ids:
            normalized_posts += list(s.scalars(
                select(NormalizedPost).where(
                    and_(NormalizedPost.source_type == SourceType.COMPETITOR,
                         NormalizedPost.source_id.in_(competitor_post_ids))
                )
            ))
        norm_ids = [np_.id for np_ in normalized_posts]

        extracted_prices = list(s.scalars(
            select(ExtractedPrice).where(ExtractedPrice.normalized_post_id.in_(norm_ids)))) if norm_ids else []
        extracted_coupons = list(s.scalars(
            select(ExtractedCoupon).where(ExtractedCoupon.normalized_post_id.in_(norm_ids)))) if norm_ids else []
        extracted_links = list(s.scalars(
            select(ExtractedLink).where(ExtractedLink.normalized_post_id.in_(norm_ids)))) if norm_ids else []

        # --- Phase 3: classification, scoped to those same normalized posts --
        post_classifications = list(s.scalars(
            select(PostClassification).where(
                PostClassification.normalized_post_id.in_(norm_ids)))) if norm_ids else []

        # --- product price history, scoped to the window ---------------------
        price_snapshots = list(
            s.scalars(select(ProductPriceSnapshot).where(
                ProductPriceSnapshot.captured_at.between(start, end)))
        )

        # --- upgrade.md Phase 2: predictions/outcomes/metric snapshots,
        # scoped to the SAME owned posts as everything else per-post above ---
        post_predictions = list(s.scalars(
            select(PostPrediction).where(PostPrediction.post_id.in_(owned_post_ids)))) if owned_post_ids else []
        post_outcomes = list(s.scalars(
            select(PostOutcome).where(PostOutcome.post_id.in_(owned_post_ids)))) if owned_post_ids else []
        post_metric_snapshots = list(s.scalars(
            select(PostMetricSnapshot).where(
                PostMetricSnapshot.post_id.in_(owned_post_ids)))) if owned_post_ids else []

        # --- reference / registry / intelligence tables: mirrored in full ----
        # (small tables; "merchants detected", profile/opportunity rows, the
        # predict/outcome/retro loop's WeeklyRetro, deal scoring history, AI
        # outputs, daily reports, campaign plans, and the subscriber/growth
        # snapshots all represent current cumulative state, not a single
        # day's slice)
        channels = list(s.scalars(select(Channel)))
        competitors = list(s.scalars(select(Competitor)))
        merchants = list(s.scalars(select(Merchant)))
        merchant_products = list(s.scalars(select(MerchantProduct)))
        discovered_domains = list(s.scalars(select(DiscoveredDomain)))
        affiliate_links = list(s.scalars(select(AffiliateLink)))
        post_type_clusters = list(s.scalars(select(PostTypeCluster)))
        merchant_profiles = list(s.scalars(select(MerchantProfile)))
        merchant_metric_windows = list(s.scalars(select(MerchantMetricWindow)))
        merchant_opportunities = list(s.scalars(select(MerchantOpportunity)))
        competitor_profiles = list(s.scalars(select(CompetitorProfile)))
        competitor_benchmarks = list(s.scalars(select(CompetitorBenchmark)))
        weekly_retros = list(s.scalars(select(WeeklyRetro)))
        deal_scores = list(s.scalars(select(DealScore)))
        ai_outputs = list(s.scalars(select(AIOutput)))
        daily_channel_reports = list(s.scalars(select(DailyChannelReport)))
        campaign_plans = list(s.scalars(select(CampaignPlan)))
        daily_subscriber_stats = list(s.scalars(select(DailySubscriberStat)))
        participant_snapshots = list(s.scalars(select(ParticipantSnapshot)))

        counts["channels"] = _upsert(dest_engine, Channel.__table__, [_row_to_dict(o) for o in channels])
        counts["competitors"] = _upsert(dest_engine, Competitor.__table__, [_row_to_dict(o) for o in competitors])
        counts["posts"] = _upsert(dest_engine, Post.__table__, [_row_to_dict(o) for o in posts])
        counts["competitor_posts"] = _upsert(
            dest_engine, CompetitorPost.__table__, [_row_to_dict(o) for o in competitor_posts])
        counts["normalized_posts"] = _upsert(
            dest_engine, NormalizedPost.__table__, [_row_to_dict(o) for o in normalized_posts])
        counts["extracted_prices"] = _upsert(
            dest_engine, ExtractedPrice.__table__, [_row_to_dict(o) for o in extracted_prices])
        counts["extracted_coupons"] = _upsert(
            dest_engine, ExtractedCoupon.__table__, [_row_to_dict(o) for o in extracted_coupons])
        counts["extracted_links"] = _upsert(
            dest_engine, ExtractedLink.__table__, [_row_to_dict(o) for o in extracted_links])
        counts["post_classifications"] = _upsert(
            dest_engine, PostClassification.__table__, [_row_to_dict(o) for o in post_classifications])
        counts["discovered_domains"] = _upsert(
            dest_engine, DiscoveredDomain.__table__, [_row_to_dict(o) for o in discovered_domains])
        counts["post_type_clusters"] = _upsert(
            dest_engine, PostTypeCluster.__table__, [_row_to_dict(o) for o in post_type_clusters])
        counts["merchants"] = _upsert(dest_engine, Merchant.__table__, [_row_to_dict(o) for o in merchants])
        counts["merchant_products"] = _upsert(
            dest_engine, MerchantProduct.__table__, [_row_to_dict(o) for o in merchant_products])
        counts["product_price_snapshots"] = _upsert(
            dest_engine, ProductPriceSnapshot.__table__, [_row_to_dict(o) for o in price_snapshots])
        counts["affiliate_links"] = _upsert(
            dest_engine, AffiliateLink.__table__, [_row_to_dict(o) for o in affiliate_links])
        counts["merchant_profiles"] = _upsert(
            dest_engine, MerchantProfile.__table__, [_row_to_dict(o) for o in merchant_profiles])
        counts["merchant_metric_windows"] = _upsert(
            dest_engine, MerchantMetricWindow.__table__, [_row_to_dict(o) for o in merchant_metric_windows])
        counts["merchant_opportunities"] = _upsert(
            dest_engine, MerchantOpportunity.__table__, [_row_to_dict(o) for o in merchant_opportunities])
        counts["competitor_profiles"] = _upsert(
            dest_engine, CompetitorProfile.__table__, [_row_to_dict(o) for o in competitor_profiles])
        counts["competitor_benchmarks"] = _upsert(
            dest_engine, CompetitorBenchmark.__table__, [_row_to_dict(o) for o in competitor_benchmarks])
        counts["post_predictions"] = _upsert(
            dest_engine, PostPrediction.__table__, [_row_to_dict(o) for o in post_predictions])
        counts["post_outcomes"] = _upsert(
            dest_engine, PostOutcome.__table__, [_row_to_dict(o) for o in post_outcomes])
        counts["post_metric_snapshots"] = _upsert(
            dest_engine, PostMetricSnapshot.__table__, [_row_to_dict(o) for o in post_metric_snapshots])
        counts["weekly_retros"] = _upsert(
            dest_engine, WeeklyRetro.__table__, [_row_to_dict(o) for o in weekly_retros])
        counts["deal_scores"] = _upsert(
            dest_engine, DealScore.__table__, [_row_to_dict(o) for o in deal_scores])
        counts["ai_outputs"] = _upsert(
            dest_engine, AIOutput.__table__, [_row_to_dict(o) for o in ai_outputs])
        counts["daily_channel_reports"] = _upsert(
            dest_engine, DailyChannelReport.__table__, [_row_to_dict(o) for o in daily_channel_reports])
        counts["campaign_plans"] = _upsert(
            dest_engine, CampaignPlan.__table__, [_row_to_dict(o) for o in campaign_plans])
        counts["daily_subscriber_stats"] = _upsert(
            dest_engine, DailySubscriberStat.__table__, [_row_to_dict(o) for o in daily_subscriber_stats])
        counts["participant_snapshots"] = _upsert(
            dest_engine, ParticipantSnapshot.__table__, [_row_to_dict(o) for o in participant_snapshots])

    dest_engine.dispose()
    return counts


# ============================================================================
# 3. MAIN
# ============================================================================

def main() -> int:
    log.info("=== collect_data starting (%s) ===", datetime.now(timezone.utc).isoformat())
    settings = get_settings()
    log.info("Source DB : %s", settings.db_url)
    log.info("Export DB : %s", ARGS.export_db_url)

    start, end = _window(ARGS.days_back, ARGS.date)

    if ARGS.dry_run:
        log.info("[dry-run] owned handles: %s", owned_handles())
        with session_scope() as s:
            comp_count = s.scalar(select(Competitor).limit(1)) is not None
        log.info("[dry-run] competitors on file: %s", "yes" if comp_count else "none yet")
        log.info("[dry-run] would export window %s -> %s (UTC) into %s",
                  start.isoformat(), end.isoformat(), ARGS.export_db_url)
        log.info("[dry-run] owned collection type: %s",
                  CollectionType.INITIAL if ARGS.initial else CollectionType.INCREMENTAL)
        log.info("[dry-run] pace_seconds=%.1f link_resolve_concurrency=%d http_timeout=%.1f",
                  ARGS.pace_seconds, ARGS.link_resolve_concurrency, ARGS.http_timeout)
        log.info("[dry-run] backtest=%s (batch_size=%d)", ARGS.backtest, ARGS.backtest_batch_size)
        return 0

    init_db()  # idempotent: creates tables in the MAIN db if this is a fresh install

    summary = RunSummary()

    if not ARGS.skip_owned:
        collect_owned(summary, ARGS.pace_seconds, ARGS.initial)
    else:
        log.info("Skipping owned-channel collection (--skip-owned).")

    if not ARGS.skip_discovery:
        discover_new_competitors(summary, ARGS.max_new_competitors, ARGS.pace_seconds)
    else:
        log.info("Skipping competitor discovery (--skip-discovery).")

    if not ARGS.skip_competitors:
        collect_competitors(summary, ARGS.pages, ARGS.pace_seconds)
    else:
        log.info("Skipping competitor collection (--skip-competitors).")

    if not ARGS.skip_normalize:
        run_normalize(summary)
    else:
        log.info("Skipping normalization (--skip-normalize).")

    if not ARGS.skip_link_resolution:
        run_link_resolution(summary, ARGS.link_resolve_limit, ARGS.link_resolve_concurrency, ARGS.http_timeout)
    else:
        log.info("Skipping link resolution (--skip-link-resolution).")

    if not ARGS.skip_classify:
        run_classify(summary, ARGS.classify_k)
    else:
        log.info("Skipping classification (--skip-classify).")

    if not ARGS.skip_merchant_intel:
        run_merchant_intel(summary)
    else:
        log.info("Skipping merchant intelligence (--skip-merchant-intel).")

    if not ARGS.skip_competitor_intel:
        run_competitor_intel(summary)
    else:
        log.info("Skipping competitor intelligence (--skip-competitor-intel).")

    # Task A.3 — backfill daily reports for the export window (idempotent,
    # runs regardless of --skip-* / --export-only).
    run_daily_reports_for_window(summary, start, end)

    # Task B — historical baseline_v1 self-eval, opt-in only.
    if ARGS.backtest:
        run_backtest_step(summary, start, end, ARGS.backtest_batch_size)
    else:
        log.info("Skipping backtest (pass --backtest to run the historical baseline_v1 self-eval).")

    try:
        counts = export_window(ARGS.export_db_url, start, end)
    except Exception:
        log.error("Export step failed:\n%s", traceback.format_exc())
        return 1

    log.info("=== Summary ===")
    log.info("Owned jobs run          : %d", len(summary.owned_jobs))
    log.info("New competitors found   : %s", (summary.discovery or {}).get("added", 0))
    log.info("Competitor jobs run     : %d", len(summary.competitor_jobs))
    log.info("Normalize               : %s", summary.normalize_job)
    log.info("Link resolution         : %s", summary.link_resolution_job)
    log.info("Classify                : %s", summary.classify_job)
    log.info("Merchant intel          : %s", summary.merchant_intel_job)
    log.info("Competitor intel        : %s", summary.competitor_intel_job)
    log.info("Daily reports           : %s", summary.daily_report_job)
    log.info("Backtest                : %s", summary.backtest_job)
    log.info("Exported -> %s : %s", ARGS.export_db_url, counts)
    if summary.errors:
        log.warning("Completed with %d error(s):", len(summary.errors))
        for e in summary.errors:
            log.warning("  - %s", e)
        return 1

    log.info("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
