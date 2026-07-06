"""Views-based analytics — descriptive statistics from the per-post view counts.

Honest scope: we have per-post VIEWS (member-visible). We do NOT have Telegram's
admin-only Statistics (subscriber growth, reach, shares-by-source) — those need
admin rights and unlock via collection/telegram_stats.py once granted.

Averages here are RAW views/post (older posts have had longer to accumulate views);
that caveat is surfaced in the UI. The age-normalized analysis lives in Insights.
Every result carries the period + sample it was computed over.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.services.analytics.periods import IST, owned_window
from src.db.models import Post
from src.db.models_classification import PostClassification, PostTypeCluster
from src.db.models_normalization import NormalizedPost, SourceType

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _owned_rows(s: Session, start=None, end=None, channel_id: int | None = None):
    """(posted_at, views, cluster_descriptor, merchant_key) for owned posts w/ views.

    Optional [start, end) UTC datetimes restrict the posting-date window.
    Optional channel_id restricts to a single owned channel (multi-tenant scoping)."""
    q = (select(Post.posted_at, Post.views, PostTypeCluster.descriptor,
                NormalizedPost.primary_merchant_key)
         .join(NormalizedPost, NormalizedPost.source_id == Post.id)
         .join(PostClassification,
               PostClassification.normalized_post_id == NormalizedPost.id, isouter=True)
         .join(PostTypeCluster, PostTypeCluster.id == PostClassification.cluster_id, isouter=True)
         .where(NormalizedPost.source_type == SourceType.OWNED, Post.views.isnot(None),
                Post.posted_at.isnot(None)))
    if channel_id is not None:
        q = q.where(Post.channel_id == channel_id)
    if start is not None:
        q = q.where(Post.posted_at >= start)
    if end is not None:
        q = q.where(Post.posted_at < end)
    return s.execute(q).all()


def _agg(pairs: dict[str, list[int]]) -> list[dict]:
    out = [{"label": k, "avg_views": round(statistics.fmean(v)), "n": len(v),
            "total_views": sum(v)} for k, v in pairs.items() if v]
    return out


def compute(s: Session, start=None, end=None, channel_id: int | None = None) -> dict:
    """All view aggregations in one pass, each with its period + sample.

    Optional [start, end) UTC datetimes restrict the window; ``window`` in the
    result reflects the actual data span within that filter. Optional channel_id
    restricts to a single owned channel."""
    rows = list(_owned_rows(s, start=start, end=end, channel_id=channel_id))

    by_day_views: dict[str, list[int]] = defaultdict(list)
    by_hour: dict[int, list[int]] = defaultdict(list)
    by_weekday: dict[str, list[int]] = defaultdict(list)
    by_type: dict[str, list[int]] = defaultdict(list)
    by_merchant: dict[str, list[int]] = defaultdict(list)

    for posted_at, views, cluster, merchant in rows:
        ist = posted_at.astimezone(IST)
        by_day_views[ist.strftime("%Y-%m-%d")].append(views)
        by_hour[ist.hour].append(views)
        by_weekday[_WEEKDAYS[ist.weekday()]].append(views)
        if cluster:
            by_type[cluster].append(views)
        if merchant:
            by_merchant[merchant].append(views)

    # views over time: up to the most recent 180 posting days in the window
    days_sorted = sorted(by_day_views.items())[-180:]
    timeline = [{"label": d, "posts": len(v), "avg_views": round(statistics.fmean(v)),
                 "total_views": sum(v)} for d, v in days_sorted]

    hour_series = [{"label": f"{h:02d}:00", "avg_views": round(statistics.fmean(by_hour[h])),
                    "n": len(by_hour[h])} for h in range(24) if by_hour.get(h)]
    weekday_series = [{"label": wd, "avg_views": round(statistics.fmean(by_weekday[wd])),
                       "n": len(by_weekday[wd])} for wd in _WEEKDAYS if by_weekday.get(wd)]
    type_series = sorted(_agg(by_type), key=lambda x: x["avg_views"], reverse=True)
    merchant_series = sorted(_agg(by_merchant), key=lambda x: x["avg_views"], reverse=True)[:10]

    # window reflects the ACTUAL data span within the filter (dates from the rows)
    dates = sorted(by_day_views.keys())
    days_span = len(dates)
    win = {"source": "owned", "start": (dates[0] if dates else None),
           "end": (dates[-1] if dates else None),
           "days": days_span, "months": round(days_span / 30.44, 1), "n": len(rows)}

    return {
        "window": win,
        "timeline": timeline,
        "by_hour": hour_series,
        "by_weekday": weekday_series,
        "by_type": type_series,
        "by_merchant": merchant_series,
        "total_posts": len(rows),
        "total_views": sum(r[1] for r in rows),
    }
