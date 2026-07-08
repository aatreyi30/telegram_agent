"""Per-day (or date-range) summary — 'what happened' from real post data.

Given an IST calendar date, or an inclusive [start, end] range of them, summarize
the owned channel's activity: per-merchant aggregates (posts, views, reactions,
forwards, top post), post-type & merchant mix, and trailing 30-day baseline
comparison.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.services.analytics.periods import IST
from src.db.models import Post, Merchant
from src.db.models_normalization import NormalizedPost, SourceType


def _ist_bounds(day: date):
    start = datetime(day.year, day.month, day.day, tzinfo=IST)
    return start, start + timedelta(days=1)


def _ist_range_bounds(day: date, end: date):
    """IST bounds for the inclusive [day, end] calendar-date range."""
    start = datetime(day.year, day.month, day.day, tzinfo=IST)
    stop = datetime(end.year, end.month, end.day, tzinfo=IST) + timedelta(days=1)
    return start, stop


def _post_type(is_multi_deal: bool) -> str:
    return "loot_deal" if is_multi_deal else "single_deal"


def _rows_between(s: Session, start, end):
    """Fetch all owned posts in [start, end) with merchant + type + deal flags.

    Returns rows: (id, posted_at, views, text, reactions_total, forwards,
                    merchant_key, has_coupon, is_multi_deal)
    """
    return s.execute(
        select(Post.id, Post.posted_at, Post.views, Post.text,
               Post.reactions_total, Post.forwards,
               NormalizedPost.primary_merchant_key,
               NormalizedPost.has_coupon, NormalizedPost.is_multi_deal)
        .join(NormalizedPost, NormalizedPost.source_id == Post.id)
        .where(NormalizedPost.source_type == SourceType.OWNED,
               Post.posted_at >= start, Post.posted_at < end)
    ).all()


def _merchant_display_names(s: Session) -> dict[str, str]:
    """Map merchant_key -> display_name for all merchants."""
    rows = s.execute(select(Merchant.key, Merchant.display_name)).all()
    return {r[0]: r[1] for r in rows}


def latest_owned_date(s: Session) -> date | None:
    """The most recent IST date on which the owned channel has a post."""
    from sqlalchemy import func

    mx = s.scalar(
        select(func.max(Post.posted_at))
        .join(NormalizedPost, NormalizedPost.source_id == Post.id)
        .where(NormalizedPost.source_type == SourceType.OWNED))
    return mx.astimezone(IST).date() if mx else None


def summarize(s: Session, day: date | None = None, end: date | None = None) -> dict:
    """Summarize owned-channel activity for an IST date, or an inclusive date range.

    ``end is None or end == day`` is the pre-filter fast path: a single calendar
    day, identical to the original single-date behavior (same query window, same
    output shape — no ``date_end`` key). ``end > day`` widens the fetch window to
    the full ``[day, end]`` range in one query; the aggregation below is already
    a single pass over whatever rows come back (sums + one running max + merged
    Counters), so it produces mathematically-correct range totals/rates/mixes
    without any extra per-day bookkeeping.
    """
    if day is None:
        day = latest_owned_date(s)
        if day is None:
            return {"date": None, "available": False, "note": "No owned posts collected yet."}
    is_range = end is not None and end != day
    start, stop = _ist_range_bounds(day, end) if is_range else _ist_bounds(day)
    rows = list(_rows_between(s, start, stop))
    if not rows:
        if is_range:
            return {"date": day.isoformat(), "date_end": end.isoformat(), "available": False,
                    "note": "No posts in this date range (IST). Pick a range within your collected range."}
        return {"date": day.isoformat(), "available": False,
                "note": "No posts on this date (IST). Pick a date within your collected range."}

    views = [r[2] for r in rows if r[2] is not None]
    total_views = sum(views)
    avg_views = round(statistics.fmean(views)) if views else 0

    # --- Per-merchant aggregates ---
    merchant_lookup = _merchant_display_names(s)

    UNKNOWN_LABEL = "__unknown__"
    merchant_buckets: dict[str, dict] = defaultdict(
        lambda: {"post_count": 0, "total_views": 0, "total_reactions": 0,
                 "total_forwards": 0, "deal_count": 0, "top_post": None, "type_dist": Counter()})
    merchantless_count = 0
    for r in rows:
        mk = r[6]
        if not mk:
            mk = UNKNOWN_LABEL
            merchantless_count += 1
        md = merchant_buckets[mk]
        md["post_count"] += 1
        md["total_views"] += (r[2] or 0)
        md["total_reactions"] += (r[4] or 0)
        md["total_forwards"] += (r[5] or 0)
        if r[7] or r[8]:       # has_coupon / is_multi_deal
            md["deal_count"] += 1
        t = _post_type(r[8])
        md["type_dist"][t] += 1
        if md["top_post"] is None or (r[2] or 0) > md["top_post"]["views"]:
            md["top_post"] = {
                "views": r[2],
                "preview": ((r[3] or "").strip().replace("\n", " ")[:90]),
            }

    merchants = sorted(
        [{"key": (None if mk == UNKNOWN_LABEL else mk),
          "display_name": ("Unknown" if mk == UNKNOWN_LABEL else merchant_lookup.get(mk, mk)),
          "post_count": md["post_count"],
          "total_views": md["total_views"],
          "total_reactions": md["total_reactions"],
          "total_forwards": md["total_forwards"],
          "total_engagement": (md["total_reactions"] or 0) + (md["total_forwards"] or 0),
          "engagement_rate": round(((md["total_reactions"] or 0) + (md["total_forwards"] or 0)) / md["total_views"] * 100, 1)
                              if md["total_views"] else None,
          "deal_count": md["deal_count"],
          "type_dist": dict(md["type_dist"].most_common()),
          "top_post": md["top_post"],
          }
         for mk, md in merchant_buckets.items()],
        key=lambda m: m["total_views"], reverse=True)

    type_mix = Counter(_post_type(r[8]) for r in rows)
    merchant_mix = Counter(r[6] for r in rows if r[6])

    # --- trailing 30-day baseline ---
    # Defined as "trailing 30 days before the window START" (`start`) — this is the
    # single definition that generalizes cleanly from a single day (excludes the day
    # itself) to a multi-day range (excludes the whole range, not just its start).
    prior_start = start - timedelta(days=30)
    prior = list(_rows_between(s, prior_start, start))
    prior_days = 30
    prior_views = [r[2] for r in prior if r[2] is not None]
    baseline = {
        "avg_posts_per_day": round(len(prior) / prior_days, 1) if prior else 0,
        "avg_views_per_post": round(statistics.fmean(prior_views)) if prior_views else 0,
        "window": f"trailing 30 days ({prior_start.date().isoformat()}→{day.isoformat()})",
    }

    result = {
        "date": day.isoformat(), "available": True,
        "posts": len(rows), "merchantless_count": merchantless_count,
        "total_views": total_views, "avg_views_per_post": avg_views,
        "merchants": merchants,
        "type_mix": type_mix.most_common(),
        "merchant_mix": merchant_mix.most_common(6),
        "baseline": baseline,
        "vs_baseline": {
            "posts_delta": len(rows) - baseline["avg_posts_per_day"],
            "views_delta_pct": (round((avg_views / baseline["avg_views_per_post"] - 1) * 100)
                                if baseline["avg_views_per_post"] else None),
        },
    }
    if is_range:
        # Extra key only present for multi-day ranges — single-day callers (and their
        # existing response shape) are unaffected.
        result["date_end"] = end.isoformat()
    return result
