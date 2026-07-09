#!/usr/bin/env python3
"""
daily_collect_and_export.py

Runs one full daily cycle for the tgagent data-collection engine — the whole
pipeline, not just raw collection:

  1. Collect fresh posts from every OWNED channel.
  2. Discover new competitor channels on Telegram (MTProto search).
  3. Collect fresh posts from every COMPETITOR channel (existing + newly discovered).
  4. Normalize raw posts -> structured NormalizedPost rows (prices, coupons,
     links, merchant detection).
  5. Resolve shortlinks (grbn.in etc.) to their real merchant.
  6. Classify posts into learned post-type clusters.
  7. Build merchant intelligence (profiles, metric windows, opportunities).
  8. Build competitor intelligence (profiles, benchmarks vs us, signals).
  9. Pull everything for "yesterday" + "today" (or one exact --date) out of
     the main operational database and mirror it into a SEPARATE, freshly
     generated .db file — channels, competitors, posts, competitor posts,
     normalized posts, extracted prices/coupons/links, classifications,
     merchants + products, and the merchant/competitor intelligence tables.

Run from the project root (the folder that contains the `src/` package),
using the same Python environment the app normally runs in:

    python scripts/daily_collect_and_export.py --date yesterday

Common flags:

    --date yesterday | today | 2026-07-08     # export exactly one calendar day
    --days-back 1                              # or a range: yesterday+today (default)
    --export-db-url sqlite:///./data/x.db      # omit to auto-name by date
    --pages 3                                  # t.me/s pages per competitor
    --max-new-competitors 5                    # discovery cap
    --link-resolve-limit 300                   # shortlinks resolved per run
    --classify-k 6                             # post-type clusters to learn
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
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Make sure "src" is importable when this script is run as
# `python scripts/daily_collect_and_export.py` from the project root.
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
                    help="Skip Phase 5 competitor intelligence (profiles/benchmarks/signals).")
    p.add_argument("--link-resolve-limit", type=int, default=300,
                    help="Max shortlinks to resolve this run (default 300).")
    p.add_argument("--classify-k", type=int, default=6,
                    help="Number of post-type clusters to learn (default 6).")
    p.add_argument("--export-only", action="store_true",
                    help="Skip ALL collection/discovery/normalization/intel stages, just export "
                         "whatever is already in the database.")
    p.add_argument("--dry-run", action="store_true",
                    help="Log what would run without touching any database.")
    p.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    return p.parse_args()


ARGS = _parse_args()

logging.basicConfig(
    level=getattr(logging, ARGS.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("daily_export")

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
from src.db.models_competitor_intel import CompetitorBenchmark, CompetitorProfile, CompetitorSignal
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
    errors: list = field(default_factory=list)


def collect_owned(summary: RunSummary) -> None:
    handles = owned_handles()
    if not handles:
        log.warning("No owned channels configured (channels table empty and OWNED_CHANNELS unset). Skipping.")
        return
    log.info("Collecting %d owned channel(s): %s", len(handles), ", ".join(handles))
    runner = JobRunner()
    for handle in handles:
        try:
            job = runner.run_collector(
                OwnedChannelCollector(handle, CollectionType.INCREMENTAL),
                collection_type=CollectionType.INCREMENTAL,
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


def discover_new_competitors(summary: RunSummary, max_add: int) -> None:
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


def collect_competitors(summary: RunSummary, pages: int) -> None:
    with session_scope() as s:
        usernames = list(
            s.scalars(select(Competitor.username).where(Competitor.username.isnot(None)))
        )
    if not usernames:
        log.warning("No competitors on file yet (table empty, discovery off/unavailable). Skipping.")
        return
    log.info("Collecting %d competitor channel(s), %d page(s) each...", len(usernames), pages)
    runner = JobRunner()
    for username in usernames:
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


def run_link_resolution(summary: RunSummary, limit: int) -> None:
    """Follow grbn.in/short links to their real merchant (fills ExtractedLink.merchant_key)."""
    from src.services.collection.link_resolution import LinkResolutionEngine

    log.info("Resolving up to %d shortlink(s)...", limit)
    try:
        job = JobRunner().run_collector(
            LinkResolutionEngine(limit=limit, delay=0.3),
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
    """Phase 5: build competitor profiles, benchmarks vs us, and threat/opportunity signals."""
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
    CompetitorProfile.__table__, CompetitorBenchmark.__table__, CompetitorSignal.__table__,
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


def export_window(export_db_url: str, days_back: int, single_date: str | None = None) -> dict:
    start, end = _window(days_back, single_date)
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

        # --- reference / registry / intelligence tables: mirrored in full ----
        # (small tables; "merchants detected" and profile/opportunity/signal
        # rows represent current cumulative state, not a single day's slice)
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
        competitor_signals = list(s.scalars(select(CompetitorSignal)))

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
        counts["competitor_signals"] = _upsert(
            dest_engine, CompetitorSignal.__table__, [_row_to_dict(o) for o in competitor_signals])

    dest_engine.dispose()
    return counts


# ============================================================================
# 3. MAIN
# ============================================================================

def main() -> int:
    log.info("=== daily_collect_and_export starting (%s) ===", datetime.now(timezone.utc).isoformat())
    settings = get_settings()
    log.info("Source DB : %s", settings.db_url)
    log.info("Export DB : %s", ARGS.export_db_url)

    if ARGS.dry_run:
        log.info("[dry-run] owned handles: %s", owned_handles())
        with session_scope() as s:
            comp_count = s.scalar(select(Competitor).limit(1)) is not None
        log.info("[dry-run] competitors on file: %s", "yes" if comp_count else "none yet")
        if ARGS.date:
            log.info("[dry-run] would export exactly one day (%s, UTC) into %s", ARGS.date, ARGS.export_db_url)
        else:
            log.info("[dry-run] would export window covering last %d day(s) + today into %s",
                      ARGS.days_back, ARGS.export_db_url)
        return 0

    init_db()  # idempotent: creates tables in the MAIN db if this is a fresh install

    summary = RunSummary()

    if not ARGS.skip_owned:
        collect_owned(summary)
    else:
        log.info("Skipping owned-channel collection (--skip-owned).")

    if not ARGS.skip_discovery:
        discover_new_competitors(summary, ARGS.max_new_competitors)
    else:
        log.info("Skipping competitor discovery (--skip-discovery).")

    if not ARGS.skip_competitors:
        collect_competitors(summary, ARGS.pages)
    else:
        log.info("Skipping competitor collection (--skip-competitors).")

    if not ARGS.skip_normalize:
        run_normalize(summary)
    else:
        log.info("Skipping normalization (--skip-normalize).")

    if not ARGS.skip_link_resolution:
        run_link_resolution(summary, ARGS.link_resolve_limit)
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

    try:
        counts = export_window(ARGS.export_db_url, ARGS.days_back, ARGS.date)
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