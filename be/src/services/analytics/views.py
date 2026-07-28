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

from src.services.analytics.periods import WEEKDAYS, to_ist
from src.services.analytics.growth import get_growth
from src.db.models import Post
from src.db.models_normalization import NormalizedPost, SourceType

# Minimum sample size for a category/discount-band/price-band bucket to appear
# in the ranked `segments` leaderboard — mirrors MIN_GOLDEN_HOUR_N's reasoning
# (a lucky post in a thin bucket shouldn't crown it). Exposed in the payload
# (segments_min_n) so the UI can render "not enough data" instead of noise.
MIN_SEGMENT_N = 3


def _owned_rows(s: Session, start=None, end=None):
    """Fetch owned posts with engagement + content signals.

    Returns rows: (posted_at, views, merchant_key,
                    reactions_total, forwards, has_coupon, is_multi_deal, cta_texts,
                    category, discount_band, price_band)
    Optional [start, end) UTC datetimes restrict the posting-date window."""
    q = (select(Post.posted_at, Post.views,
                NormalizedPost.primary_merchant_key,
                Post.reactions_total, Post.forwards,
                NormalizedPost.has_coupon, NormalizedPost.is_multi_deal,
                NormalizedPost.cta_texts,
                NormalizedPost.category, NormalizedPost.discount_band,
                NormalizedPost.price_band)
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
    by_category: dict[str, list[tuple]] = defaultdict(list)
    by_discount_band: dict[str, list[tuple]] = defaultdict(list)
    by_price_band: dict[str, list[tuple]] = defaultdict(list)

    # Column indices for readability
    I_VIEWS = 1
    I_REACTIONS = 3
    I_FORWARDS = 4
    I_COUPON = 5
    I_MULTI = 6
    I_CTA = 7
    I_CATEGORY = 8
    I_DISCOUNT_BAND = 9
    I_PRICE_BAND = 10

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
        by_weekday[WEEKDAYS[ist.weekday()]].append(tup)
        t = "loot_deal" if r[I_MULTI] else "single_deal"
        by_type[t].append(tup)
        mk = r[2]  # merchant_key
        if mk:
            by_merchant[mk].append(tup)
        if r[I_CATEGORY]:
            by_category[r[I_CATEGORY]].append(tup)
        if r[I_DISCOUNT_BAND]:
            by_discount_band[r[I_DISCOUNT_BAND]].append(tup)
        if r[I_PRICE_BAND]:
            by_price_band[r[I_PRICE_BAND]].append(tup)

    # ------- coverage: how many of this window's posts actually carry each
    # dimension, so the UI can say "this leaderboard covers 31% of the
    # window's posts" instead of implying every post was counted -------
    total_posts_n = len(rows)
    dimension_coverage = {
        "category": {"categorized": sum(len(v) for v in by_category.values()),
                      "total": total_posts_n},
        "discount_band": {"categorized": sum(len(v) for v in by_discount_band.values()),
                           "total": total_posts_n},
        "price_band": {"categorized": sum(len(v) for v in by_price_band.values()),
                        "total": total_posts_n},
    }

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
    weekday_series = [{"label": wd, **_reduce(by_weekday.get(wd, []))} for wd in WEEKDAYS]

    # ------- by type -------
    type_series = sorted(
        [{"label": k, **_reduce(v)} for k, v in by_type.items()],
        key=lambda x: x["total_views"], reverse=True)

    # ------- by merchant (top 10) -------
    merchant_series = sorted(
        [{"label": k, **_reduce(v)} for k, v in by_merchant.items()],
        key=lambda x: x["total_views"], reverse=True)[:10]

    # ------- by category / discount band / price band -------
    # These raw breakdowns are ungated (unlike `segments`), so each row carries
    # `below_min_n` — an n=1 bucket at 100% engagement is real data, but the UI
    # must be able to mark it as a sub-sample rather than render it as the
    # tallest, most confident bar next to a leaderboard that gates on sample size.
    category_series = sorted(
        [{"label": k, "below_min_n": len(v) < MIN_SEGMENT_N, **_reduce(v)}
         for k, v in by_category.items()],
        key=lambda x: x["total_views"], reverse=True)
    discount_band_series = sorted(
        [{"label": k, "below_min_n": len(v) < MIN_SEGMENT_N, **_reduce(v)}
         for k, v in by_discount_band.items()],
        key=lambda x: x["total_views"], reverse=True)
    price_band_series = sorted(
        [{"label": k, "below_min_n": len(v) < MIN_SEGMENT_N, **_reduce(v)}
         for k, v in by_price_band.items()],
        key=lambda x: x["total_views"], reverse=True)

    # ------- segments: dimension buckets ranked by engagement rate -------
    # A minimum sample size gate (mirrors MIN_GOLDEN_HOUR_N above) so a single
    # lucky post in a thin bucket can't top the leaderboard as noise — the
    # payload states the gate so the UI can say "not enough data" instead of
    # silently hiding or, worse, showing an unreliable rank.
    segments = sorted(
        [
            {"dimension": dim, "label": row["label"], **row}
            for dim, series in (
                ("category", category_series),
                ("discount_band", discount_band_series),
                ("price_band", price_band_series),
            )
            for row in series
            if row["n"] >= MIN_SEGMENT_N
        ],
        key=lambda x: x["engagement_rate"], reverse=True,
    )

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
        "by_category": category_series,
        "by_discount_band": discount_band_series,
        "by_price_band": price_band_series,
        "segments": segments,
        "segments_min_n": MIN_SEGMENT_N,
        "dimension_coverage": dimension_coverage,
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


def segment_performance(s: Session, top_n: int = 3) -> dict:
    """Top/bottom categories and discount bands by engagement rate (gated at
    MIN_SEGMENT_N), for the daily-plan's grounding context (AC5) — so a slot's
    `why` can cite a dimension-level number instead of the channel average.

    Carries the ``window`` its numbers actually span, same as every other
    fact fed to the plan — this product's whole promise is that no number
    ships unlabelled."""
    full = compute(s)
    segs = full["segments"]
    cats = [row for row in segs if row["dimension"] == "category"]
    bands = [row for row in segs if row["dimension"] == "discount_band"]

    def _top_bottom(ranked: list[dict]) -> tuple[list[dict], list[dict]]:
        # Disjoint by construction: bottom is drawn only from what's left
        # after top is removed, so a row can never be both "top" and
        # "bottom" (the old `ranked[-top_n:]` could overlap `ranked[:top_n]`
        # whenever top_n < len(ranked) <= 2 * top_n).
        top = ranked[:top_n]
        remaining = ranked[top_n:]
        bottom = remaining[-top_n:] if remaining else []
        return top, bottom

    top_categories, bottom_categories = _top_bottom(cats)
    top_discount_bands, bottom_discount_bands = _top_bottom(bands)

    return {
        "available": bool(cats or bands),
        "min_n": MIN_SEGMENT_N,
        "window": full["window"],
        "top_categories": top_categories,
        "bottom_categories": bottom_categories,
        "top_discount_bands": top_discount_bands,
        "bottom_discount_bands": bottom_discount_bands,
    }
