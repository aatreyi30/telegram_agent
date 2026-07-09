"""Analytics — views, reactions, forwards, engagement, CTA, deals, and growth.

Honest scope: we have per-post views, reactions_total, and forwards (member-visible,
from MTProto). We also have content flags (has_coupon, is_multi_deal, cta_texts)
from the normalization engine. Telegram's admin-only Statistics (subscriber growth,
reach, shares-by-source) remain unavailable until admin rights are granted.

Averages are RAW views/post (older posts have accumulated more views); that caveat
is surfaced in the UI. Every result carries its period + sample size.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.services.analytics.periods import to_ist
from src.services.analytics.growth import get_growth
from src.db.models import Post
from src.db.models_normalization import NormalizedPost, SourceType

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _owned_rows(s: Session, start=None, end=None):
    """Fetch owned posts with engagement + content signals.

    Returns rows: (posted_at, views, merchant_key,
                    reactions_total, forwards, has_coupon, is_multi_deal, cta_texts)
    Optional [start, end) UTC datetimes restrict the posting-date window."""
    q = (select(Post.posted_at, Post.views,
                NormalizedPost.primary_merchant_key,
                Post.reactions_total, Post.forwards,
                NormalizedPost.has_coupon, NormalizedPost.is_multi_deal,
                NormalizedPost.cta_texts)
         .join(NormalizedPost, NormalizedPost.source_id == Post.id)
         .where(NormalizedPost.source_type == SourceType.OWNED, Post.views.isnot(None),
                Post.posted_at.isnot(None)))
    if start is not None:
        q = q.where(Post.posted_at >= start)
    if end is not None:
        q = q.where(Post.posted_at < end)
    return s.execute(q).all()


def _fmean(vals: list[int | None]) -> float:
    vals = [v for v in vals if v is not None]
    return statistics.fmean(vals) if vals else 0.0


def _agg_metric(buckets: dict[str, list[int]]) -> list[dict]:
    return [{"label": k, "avg_views": round(_fmean(v)), "n": len(v),
             "total_views": sum(v)} for k, v in buckets.items() if v]


def compute(s: Session, start=None, end=None) -> dict:
    """Full analytics — one pass over owned posts.

    Optional [start, end) UTC datetimes restrict the window; ``window`` in the
    result reflects the actual data span within that filter."""
    rows = list(_owned_rows(s, start=start, end=end))

    # Buckets keyed by dimension → list of (views, reactions, forwards, is_cta, is_deal)
    by_day: dict[str, list[tuple]] = defaultdict(list)
    by_hour: dict[int, list[tuple]] = defaultdict(list)
    by_weekday: dict[str, list[tuple]] = defaultdict(list)
    by_type: dict[str, list[tuple]] = defaultdict(list)
    by_merchant: dict[str, list[tuple]] = defaultdict(list)

    # Column indices for readability
    I_VIEWS = 1
    I_REACTIONS = 3
    I_FORWARDS = 4
    I_COUPON = 5
    I_MULTI = 6
    I_CTA = 7

    for r in rows:
        ist = to_ist(r[0])
        day_key = ist.strftime("%Y-%m-%d")
        views = r[I_VIEWS] or 0
        reactions = r[I_REACTIONS] or 0
        forwards = r[I_FORWARDS] or 0
        has_cta = bool(r[I_CTA])                 # non-empty list
        is_deal = bool(r[I_COUPON]) or bool(r[I_MULTI])
        tup = (views, reactions, forwards, has_cta, is_deal)

        by_day[day_key].append(tup)
        by_hour[ist.hour].append(tup)
        by_weekday[_WEEKDAYS[ist.weekday()]].append(tup)
        t = "loot_deal" if r[I_MULTI] else "single_deal"
        by_type[t].append(tup)
        mk = r[2]  # merchant_key
        if mk:
            by_merchant[mk].append(tup)

    # ------- helper: reduce a list of tuples -------
    def _reduce(tups: list[tuple]) -> dict:
        n = len(tups)
        if not n:
            return {"n": 0, "avg_views": 0, "median_views": 0, "total_views": 0,
                    "total_reactions": 0, "total_forwards": 0,
                    "total_engagement": 0, "engagement_rate": 0,
                    "cta_posts": 0, "deal_posts": 0}
        v = [t[0] for t in tups]
        rct = [t[1] for t in tups]
        fwd = [t[2] for t in tups]
        sv = sum(v)
        sr = sum(rct)
        sf = sum(fwd)
        return {
            "n": n,
            "avg_views": round(_fmean(v)),
            "median_views": round(statistics.median(v)) if v else 0,
            "total_views": sv,
            "total_reactions": sr,
            "total_forwards": sf,
            "total_engagement": sr + sf,
            "engagement_rate": round((sr + sf) / sv * 100, 1) if sv else 0,
            "cta_posts": sum(1 for t in tups if t[3]),
            "deal_posts": sum(1 for t in tups if t[4]),
        }

    # ------- timeline (daily, capped at 180 days) -------
    days_sorted = sorted(by_day.items())[-180:]
    timeline = [{"label": d, **_reduce(v)} for d, v in days_sorted]

    # ------- by hour (all 24, even empty) -------
    hour_series = [{"label": f"{h:02d}:00", **_reduce(by_hour.get(h, []))} for h in range(24)]

    # ------- by weekday -------
    weekday_series = [{"label": wd, **_reduce(by_weekday.get(wd, []))} for wd in _WEEKDAYS]

    # ------- by type -------
    type_series = sorted(
        [{"label": k, **_reduce(v)} for k, v in by_type.items()],
        key=lambda x: x["total_views"], reverse=True)

    # ------- by merchant (top 10) -------
    merchant_series = sorted(
        [{"label": k, **_reduce(v)} for k, v in by_merchant.items()],
        key=lambda x: x["total_views"], reverse=True)[:10]

    # ------- golden hours: top 3 hours by median views/post, views-only -------
    # A per-post efficiency question, not a volume one — median (not mean) so a
    # single viral post can't crown an hour, and a minimum sample size so a lucky
    # post at a low-volume hour can't either. Threshold mirrors the "post_count >= 3"
    # gate used for merchant window confidence in src/services/intelligence/merchant.py.
    MIN_GOLDEN_HOUR_N = 3
    hour_stats = [(h, _reduce(by_hour.get(h, []))) for h in range(24) if by_hour.get(h)]
    eligible_hour_stats = [(h, hs) for h, hs in hour_stats if hs["n"] >= MIN_GOLDEN_HOUR_N]
    golden_by_views = sorted(eligible_hour_stats, key=lambda x: x[1]["median_views"], reverse=True)[:3]
    golden_hours = [{"hour": f"{h:02d}:00", **hs} for h, hs in golden_by_views]

    # ------- aggregate totals -------
    all_agg = _reduce([tup for _, tups in by_day.items() for tup in tups])

    # ------- window metadata -------
    # sort the day keys — dict insertion order is row order, not chronological, so
    # start/end must come from the sorted min/max, not the first/last inserted key.
    dates = sorted(by_day.keys())
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
        "golden_hours": golden_hours,
        "growth": get_growth(s, start, end),
        "total_posts": all_agg["n"],
        "total_views": all_agg["total_views"],
        "total_reactions": all_agg["total_reactions"],
        "total_forwards": all_agg["total_forwards"],
        "total_engagement": all_agg["total_engagement"],
        "engagement_rate": all_agg["engagement_rate"],
        "cta_rate": round(all_agg["cta_posts"] / all_agg["n"] * 100, 1) if all_agg["n"] else 0,
        "deal_rate": round(all_agg["deal_posts"] / all_agg["n"] * 100, 1) if all_agg["n"] else 0,
    }
