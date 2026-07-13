"""Phase 2.4 -- RetroEngine: turns last week's Predict -> Outcome data into a
concrete, ruled set of plan adjustments plus a narrative, stored as one
``WeeklyRetro`` row per IST week (Monday start).

Design (Section 2.4 of upgrade.md, scope-trimmed -- no Phase-1 joins/leaves
attribution, out of scope this pass):
  * ``prediction`` -- MAPE/bias of ``post_outcomes.err_views_24h`` over the week.
  * ``top_over``/``top_under`` -- the biggest prediction misses either way.
  * ``plan_adherence`` -- planned vs published vs blocked_stale vs skipped, from
    ``ScheduledPost`` rows scheduled in the week (0.3's ``blocked_stale:`` note
    prefix on ``ScheduledPost.last_error`` identifies pre-publish-revalidation
    blocks specifically, vs. e.g. missing-admin-rights blocks).
  * ``engagement`` -- median forward rate, best hour bucket / post type by mean
    ``engagement_score`` this week.
  * ``churn_vs_frequency`` -- posts/day on the 7 worst- vs 7 best-churn days of
    the last 28 (``daily_subscriber_stats.subs_left``) -- the "are we
    over-posting" signal.
  * ``adjustments`` -- DETERMINISTIC threshold rules (NOT AI): hour buckets at
    or above the p75 of this week's per-bucket mean engagement (n>=5 posts)
    get a "shift toward" note; merchants/types at or below p25 (n>=5) get a
    "reduce" note. Reuses ``engagement.pct`` (the same percentile primitive
    ``engagement_score`` itself is built from) rather than re-deriving ranking.
  * ``narrative`` -- ``insight_writer.narrate`` (AI phrasing, deterministic
    fallback) -- persisted on the row AND via ``record_ai_output`` (0.2).

All grouping/threshold math here operates over the retro's own week (7 days,
IST Monday->Sunday). The ``engagement_score`` values it reads are ALREADY
normalized against each post's channel's own last-28-day distribution
(``engagement.py``), so comparing weekly means across buckets/merchants stays
apples-to-apples without needing a second rolling window here.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import mean, median

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.ai.insight_writer import narrate
from src.config.settings import get_settings
from src.db.models import Channel, Post
from src.db.models_automation import ScheduledPost, ScheduleStatus
from src.db.models_classification import PostClassification, PostTypeCluster
from src.db.models_growth_snapshot import DailySubscriberStat
from src.db.models_normalization import NormalizedPost, SourceType
from src.db.models_prediction import PostOutcome, PostPrediction, WeeklyRetro
from src.services.ai_outputs import record_ai_output
from src.services.analytics.engagement import pct
from src.services.analytics.periods import ist_range_bounds_utc, to_ist
from src.services.analytics.prediction import day_class, hour_bucket
from src.logger import get_logger

logger = get_logger(__name__)

MIN_ADJUSTMENT_SAMPLES = 5     # a bucket/merchant/type needs >=5 posts to be trusted
ADJUST_HIGH_PCT = 0.75
ADJUST_LOW_PCT = 0.25
TOP_N_MISSES = 3
CHURN_LOOKBACK_DAYS = 28
CHURN_SAMPLE_DAYS = 7


def _owned_channel(s: Session) -> Channel | None:
    """Same "the owned channel" resolution as ``daily_report.py`` -- imported
    lazily (repo convention) to avoid a module-load cycle with analytics.day."""
    from src.services.analytics.daily_report import _owned_channel as _resolve

    return _resolve(s)


def _week_posts(s: Session, channel_id: int | None, week_start: date, week_end: date) -> list[dict]:
    """One row per owned post posted in [week_start, week_end] IST, joined to
    its outcome/prediction/type/merchant facts -- the shared basis every
    metrics section below reads from. Empty when there's no owned channel."""
    if channel_id is None:
        return []
    start_utc, end_utc = ist_range_bounds_utc(week_start, week_end)
    posts = s.execute(
        select(Post.id, Post.posted_at).where(
            Post.channel_id == channel_id,
            Post.posted_at >= start_utc,
            Post.posted_at < end_utc,
        )
    ).all()
    if not posts:
        return []
    post_ids = [p[0] for p in posts]

    outcomes = {
        o.post_id: o for o in s.scalars(select(PostOutcome).where(PostOutcome.post_id.in_(post_ids)))
    }
    preds = {
        p.post_id: p for p in s.scalars(select(PostPrediction).where(PostPrediction.post_id.in_(post_ids)))
    }
    norm_rows = s.execute(
        select(NormalizedPost.source_id, NormalizedPost.primary_merchant_key, PostClassification.cluster_id)
        .outerjoin(PostClassification, PostClassification.normalized_post_id == NormalizedPost.id)
        .where(NormalizedPost.source_type == SourceType.OWNED, NormalizedPost.source_id.in_(post_ids))
    ).all()
    merchant_by_post = {r[0]: r[1] for r in norm_rows}
    cluster_by_post = {r[0]: r[2] for r in norm_rows}
    cluster_ids = {c for c in cluster_by_post.values() if c is not None}
    descriptor_by_cluster: dict[int, str | None] = {}
    if cluster_ids:
        descriptor_by_cluster = dict(
            s.execute(
                select(PostTypeCluster.id, PostTypeCluster.descriptor)
                .where(PostTypeCluster.id.in_(cluster_ids))
            ).all()
        )

    rows: list[dict] = []
    for pid, posted_at in posts:
        if posted_at is None:
            continue
        pat_ist = to_ist(posted_at)
        outcome = outcomes.get(pid)
        pred = preds.get(pid)
        cluster_id = cluster_by_post.get(pid)
        type_label = descriptor_by_cluster.get(cluster_id) if cluster_id is not None else None
        if cluster_id is not None and not type_label:
            type_label = f"cluster_{cluster_id}"
        rows.append({
            "post_id": pid,
            "hour_bucket": hour_bucket(pat_ist.hour),
            "day_class": day_class(pat_ist),
            "merchant": merchant_by_post.get(pid),
            "type_label": type_label,
            "engagement_score": outcome.engagement_score if outcome else None,
            "forward_rate": outcome.forward_rate if outcome else None,
            "views_24h": outcome.views_24h if outcome else None,
            "err_views_24h": outcome.err_views_24h if outcome else None,
            "predicted_views_24h": pred.predicted_views_24h if pred else None,
        })
    return rows


def _prediction_summary(rows: list[dict]) -> dict:
    errs = [r["err_views_24h"] for r in rows if r["err_views_24h"] is not None]
    if not errs:
        return {"mape_views_24h": None, "n_posts": 0, "bias": None}
    return {
        "mape_views_24h": round(mean(abs(e) for e in errs), 4),
        "n_posts": len(errs),
        "bias": round(mean(errs), 4),
    }


def _top_misses(rows: list[dict], n: int = TOP_N_MISSES) -> tuple[list[dict], list[dict]]:
    scored = [r for r in rows if r["err_views_24h"] is not None and r["predicted_views_24h"]]

    def _fmt(r: dict) -> dict:
        return {
            "post_id": r["post_id"], "pred": r["predicted_views_24h"], "actual": r["views_24h"],
            "type": r["type_label"], "merchant": r["merchant"],
        }

    over = sorted(scored, key=lambda r: r["err_views_24h"], reverse=True)[:n]
    under = sorted(scored, key=lambda r: r["err_views_24h"])[:n]
    return [_fmt(r) for r in over], [_fmt(r) for r in under]


def _plan_adherence(s: Session, week_start: date, week_end: date) -> dict:
    start_utc, end_utc = ist_range_bounds_utc(week_start, week_end)
    scheduled = s.scalars(
        select(ScheduledPost).where(
            ScheduledPost.scheduled_at >= start_utc, ScheduledPost.scheduled_at < end_utc
        )
    ).all()
    planned = len(scheduled)
    published = sum(1 for r in scheduled if r.status == ScheduleStatus.PUBLISHED)
    blocked_stale = sum(
        1 for r in scheduled
        if r.status == ScheduleStatus.BLOCKED and (r.last_error or "").startswith("blocked_stale")
    )
    skipped = max(planned - published - blocked_stale, 0)
    return {"planned": planned, "published": published, "blocked_stale": blocked_stale, "skipped": skipped}


def _engagement_summary(rows: list[dict]) -> dict:
    fwd_rates = [r["forward_rate"] for r in rows if r["forward_rate"] is not None]
    median_forward_rate = round(median(fwd_rates), 4) if fwd_rates else None

    by_bucket: dict[str, list[float]] = defaultdict(list)
    by_type: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r["engagement_score"] is None:
            continue
        by_bucket[r["hour_bucket"]].append(r["engagement_score"])
        if r["type_label"]:
            by_type[r["type_label"]].append(r["engagement_score"])

    best_hour_bucket = max(by_bucket, key=lambda k: mean(by_bucket[k])) if by_bucket else None
    best_type_by_engagement = max(by_type, key=lambda k: mean(by_type[k])) if by_type else None

    return {
        "median_forward_rate": median_forward_rate,
        "best_hour_bucket": best_hour_bucket,
        "best_type_by_engagement": best_type_by_engagement,
    }


def _churn_vs_frequency(s: Session, channel_id: int | None, week_end: date) -> dict:
    """Mean posts/day on the 7 worst- vs 7 best-churn days (by ``subs_left``)
    of the last 28 days ending ``week_end`` -- the over-posting signal."""
    empty = {"high_leave_days_posts_per_day": None, "low_leave_days_posts_per_day": None}
    if channel_id is None:
        return empty

    start_day = week_end - timedelta(days=CHURN_LOOKBACK_DAYS - 1)
    stats = s.scalars(
        select(DailySubscriberStat).where(
            DailySubscriberStat.channel_id == channel_id,
            DailySubscriberStat.stat_date >= start_day,
            DailySubscriberStat.stat_date <= week_end,
        )
    ).all()
    # need at least two DISTINCT days to draw a worst-vs-best contrast at all
    if len({r.stat_date for r in stats}) < 2:
        return empty

    start_utc, end_utc = ist_range_bounds_utc(start_day, week_end)
    post_rows = s.execute(
        select(Post.posted_at).where(
            Post.channel_id == channel_id, Post.posted_at >= start_utc, Post.posted_at < end_utc
        )
    ).all()
    counts: dict[date, int] = defaultdict(int)
    for (posted_at,) in post_rows:
        if posted_at is not None:
            counts[to_ist(posted_at).date()] += 1

    ranked = sorted(stats, key=lambda r: (r.subs_left or 0), reverse=True)
    worst = ranked[:CHURN_SAMPLE_DAYS]
    best = ranked[-CHURN_SAMPLE_DAYS:]

    def _avg_posts(days) -> float | None:
        if not days:
            return None
        return round(mean(counts.get(d.stat_date, 0) for d in days), 2)

    return {
        "high_leave_days_posts_per_day": _avg_posts(worst),
        "low_leave_days_posts_per_day": _avg_posts(best),
    }


def _group_means(groups: dict[str, list[float]]) -> dict[str, float]:
    return {k: mean(v) for k, v in groups.items() if len(v) >= MIN_ADJUSTMENT_SAMPLES}


def _adjustments(rows: list[dict]) -> list[str]:
    """Deterministic threshold rules (Section 2.4) -- NOT AI. Reuses
    ``engagement.pct`` to rank each group's own mean ``engagement_score``
    against its siblings (hour buckets against hour buckets, merchants against
    merchants, types against types)."""
    by_bucket: dict[str, list[float]] = defaultdict(list)
    by_merchant: dict[str, list[float]] = defaultdict(list)
    by_type: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        score = r["engagement_score"]
        if score is None:
            continue
        by_bucket[r["hour_bucket"]].append(score)
        if r["merchant"]:
            by_merchant[r["merchant"]].append(score)
        if r["type_label"]:
            by_type[r["type_label"]].append(score)

    adjustments: list[str] = []

    bucket_means = _group_means(by_bucket)
    if len(bucket_means) > 1:
        pool = list(bucket_means.values())
        for bucket, m in sorted(bucket_means.items()):
            rank = pct(m, pool)
            if rank >= ADJUST_HIGH_PCT:
                adjustments.append(
                    f"shift toward {bucket} bucket (engagement p{int(round(rank * 100))}, "
                    f"n={len(by_bucket[bucket])})"
                )

    def _reduce_rule(groups: dict[str, list[float]], label: str) -> None:
        means_ = _group_means(groups)
        if len(means_) <= 1:
            return
        pool = list(means_.values())
        for key, m in sorted(means_.items()):
            rank = pct(m, pool)
            if rank <= ADJUST_LOW_PCT:
                adjustments.append(
                    f"reduce {label} {key}: engagement p{int(round(rank * 100))} vs channel median "
                    f"(n={len(groups[key])})"
                )

    _reduce_rule(by_merchant, "merchant")
    _reduce_rule(by_type, "type")
    return adjustments


def _narrative_observation(week_start: date, metrics: dict) -> tuple[str, str]:
    """Returns ``(observation, fallback)`` for ``insight_writer.narrate`` --
    the fallback is a good, data-specific sentence entirely on its own."""
    pred = metrics["prediction"]
    adherence = metrics["plan_adherence"]
    n_adj = len(metrics["adjustments"])

    if pred["n_posts"]:
        observation = (
            f"Week of {week_start.isoformat()}: {pred['n_posts']} predicted posts, "
            f"MAPE {pred['mape_views_24h']:.2f}, bias {pred['bias']:+.2f}; "
            f"{adherence['published']}/{adherence['planned']} planned posts published "
            f"({adherence['blocked_stale']} blocked stale, {adherence['skipped']} skipped); "
            f"{n_adj} rule-based adjustment(s) for next week."
        )
    else:
        observation = (
            f"Week of {week_start.isoformat()}: no posts with a linked prediction this week; "
            f"{adherence['published']}/{adherence['planned']} planned posts published "
            f"({adherence['blocked_stale']} blocked stale, {adherence['skipped']} skipped); "
            f"{n_adj} rule-based adjustment(s) for next week."
        )
    fallback = observation
    if metrics["adjustments"]:
        fallback += " Adjustments: " + "; ".join(metrics["adjustments"]) + "."
    return observation, fallback


def build_weekly_retro(s: Session, week_start: date) -> WeeklyRetro:
    """Build (or refresh) the ``WeeklyRetro`` row for the IST week starting
    ``week_start`` (a Monday). Idempotent per week -- reruns for the same
    ``week_start`` update the existing row in place rather than duplicating it
    (mirrors the ``weekly_brief``/``CampaignPlan`` reuse pattern)."""
    week_end = week_start + timedelta(days=6)
    ch = _owned_channel(s)
    channel_id = ch.id if ch else None

    rows = _week_posts(s, channel_id, week_start, week_end)
    metrics = {
        "prediction": _prediction_summary(rows),
        "plan_adherence": _plan_adherence(s, week_start, week_end),
        "engagement": _engagement_summary(rows),
        "churn_vs_frequency": _churn_vs_frequency(s, channel_id, week_end),
    }
    top_over, top_under = _top_misses(rows)
    metrics["top_over"] = top_over
    metrics["top_under"] = top_under
    metrics["adjustments"] = _adjustments(rows)

    observation, fallback = _narrative_observation(week_start, metrics)
    narrative = narrate("weekly_retro", observation, metrics, fallback)

    row = s.scalar(select(WeeklyRetro).where(WeeklyRetro.week_start == week_start))
    if row is None:
        row = WeeklyRetro(week_start=week_start)
        s.add(row)
    row.metrics = metrics
    row.narrative = narrative
    s.flush()

    # Reuse the caller's own (still-open, uncommitted) session `s` rather than
    # letting record_ai_output open a second writer connection -- on SQLite that
    # second connection blocks on this transaction's write lock and raises
    # "database is locked" once busy_timeout elapses (see ai_outputs.py docstring).
    record_ai_output("retro_narrative", narrative, get_settings().ai_model, session=s)
    return row
