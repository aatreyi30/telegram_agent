"""Per-day summary — 'what happened on this date' from real post data.

Given an IST calendar date, summarize the owned channel's activity that day:
posts, total/avg views, top posts, post-type & merchant mix, and how the day
compares to the trailing 30-day average. All from per-post views (member data).
"""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.services.analytics.periods import IST
from src.db.models import Post
from src.db.models_classification import PostClassification, PostTypeCluster
from src.db.models_normalization import NormalizedPost, SourceType


def _ist_bounds(day: date):
    start = datetime(day.year, day.month, day.day, tzinfo=IST)
    return start, start + timedelta(days=1)


def _rows_between(s: Session, start, end, channel_id: int | None = None):
    q = (select(Post.id, Post.posted_at, Post.views, Post.text,
                PostTypeCluster.descriptor, NormalizedPost.primary_merchant_key)
         .join(NormalizedPost, NormalizedPost.source_id == Post.id)
         .join(PostClassification,
               PostClassification.normalized_post_id == NormalizedPost.id, isouter=True)
         .join(PostTypeCluster, PostTypeCluster.id == PostClassification.cluster_id, isouter=True)
         .where(NormalizedPost.source_type == SourceType.OWNED,
                Post.posted_at >= start, Post.posted_at < end))
    if channel_id is not None:
        q = q.where(Post.channel_id == channel_id)
    return s.execute(q).all()


def latest_owned_date(s: Session, channel_id: int | None = None) -> date | None:
    """The most recent IST date on which the owned channel has a post."""
    from sqlalchemy import func

    q = (select(func.max(Post.posted_at))
         .join(NormalizedPost, NormalizedPost.source_id == Post.id)
         .where(NormalizedPost.source_type == SourceType.OWNED))
    if channel_id is not None:
        q = q.where(Post.channel_id == channel_id)
    mx = s.scalar(q)
    return mx.astimezone(IST).date() if mx else None


def summarize(s: Session, day: date | None = None, channel_id: int | None = None) -> dict:
    # default to the latest date that actually has posts (not calendar "today",
    # which may be after the last collection and would look empty)
    if day is None:
        day = latest_owned_date(s, channel_id=channel_id)
        if day is None:
            return {"date": None, "available": False, "note": "No owned posts collected yet."}
    start, end = _ist_bounds(day)
    rows = list(_rows_between(s, start, end, channel_id=channel_id))
    if not rows:
        return {"date": day.isoformat(), "available": False,
                "note": "No posts on this date (IST). Pick a date within your collected range."}

    views = [r[2] for r in rows if r[2] is not None]
    total_views = sum(views)
    avg_views = round(statistics.fmean(views)) if views else 0

    # top posts by views
    top = sorted([r for r in rows if r[2] is not None], key=lambda r: r[2], reverse=True)[:5]
    top_posts = [{"views": r[2], "type": r[4] or "unclassified",
                  "merchant": r[5] or "unknown",
                  "preview": ((r[3] or "").strip().replace("\n", " ")[:90])} for r in top]

    type_mix = Counter(r[4] or "unclassified" for r in rows)
    merchant_mix = Counter(r[5] for r in rows if r[5])

    # trailing 30-day average posts/day + avg views/post (excludes the day itself)
    prior_start = start - timedelta(days=30)
    prior = list(_rows_between(s, prior_start, start, channel_id=channel_id))
    prior_days = 30
    prior_views = [r[2] for r in prior if r[2] is not None]
    baseline = {
        "avg_posts_per_day": round(len(prior) / prior_days, 1) if prior else 0,
        "avg_views_per_post": round(statistics.fmean(prior_views)) if prior_views else 0,
        "window": f"trailing 30 days ({prior_start.date().isoformat()}→{day.isoformat()})",
    }

    return {
        "date": day.isoformat(), "available": True,
        "posts": len(rows), "total_views": total_views, "avg_views_per_post": avg_views,
        "top_posts": top_posts,
        "type_mix": type_mix.most_common(),
        "merchant_mix": merchant_mix.most_common(6),
        "baseline": baseline,
        "vs_baseline": {
            "posts_delta": len(rows) - baseline["avg_posts_per_day"],
            "views_delta_pct": (round((avg_views / baseline["avg_views_per_post"] - 1) * 100)
                                if baseline["avg_views_per_post"] else None),
        },
    }
