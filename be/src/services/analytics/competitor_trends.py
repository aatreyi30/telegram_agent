"""Per-competitor DAILY TIME-SERIES charts (Phase 2 of competitor analytics).

Lifetime (non-trend) competitor metrics already live in metrics/competitor_metrics.py
and are exposed via /api/competitor-dashboard — this module is only the day-bucketed
views of the same underlying data (plus a couple of ranked/histogram queries that
don't exist anywhere yet). Every daily bucket goes through periods.py's IST helpers;
see test_ist_day_boundary.py for why a naive UTC-day bucketing is a real, previously
shipped bug.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import CompetitorPost
from src.db.models_normalization import NormalizedPost, SourceType
from src.services.analytics.day import _post_type
from src.services.analytics.periods import ist_day_bounds_utc, to_ist

TOP_MERCHANTS_N = 8
TEXT_SNIPPET_LEN = 140
LENGTH_BUCKETS = [(0, 50), (50, 100), (100, 200), (200, 400), (400, None)]


def _latest_date(s: Session, competitor_id: int) -> date | None:
    mx = s.scalar(
        select(func.max(CompetitorPost.posted_at))
        .where(CompetitorPost.competitor_id == competitor_id))
    return to_ist(mx).date() if mx else None


def _window(s: Session, competitor_id: int, days: int):
    """(first_day, end_day, start_utc, end_utc) for the trailing `days`-day IST window
    ending at this competitor's most recent post, or None with no dated posts at all —
    same "end at latest observed data, not at wall-clock now" anchor as posting_trajectory."""
    end_day = _latest_date(s, competitor_id)
    if end_day is None:
        return None
    first_day = end_day - timedelta(days=days - 1)
    start_utc, _ = ist_day_bounds_utc(first_day)
    _, end_utc = ist_day_bounds_utc(end_day)
    return first_day, end_day, start_utc, end_utc


def _day_range(first_day: date, days: int):
    for i in range(days):
        yield first_day + timedelta(days=i)


def posting_trend(s: Session, competitor_id: int, days: int = 30) -> dict:
    """Posts-per-day. Also the source series for "Daily Posting Frequency" — same
    data, just rendered as a different chart type by the frontend."""
    win = _window(s, competitor_id, days)
    if win is None:
        return {"days": []}
    first_day, _, start_utc, end_utc = win
    rows = s.execute(
        select(CompetitorPost.posted_at)
        .where(CompetitorPost.competitor_id == competitor_id,
               CompetitorPost.posted_at >= start_utc, CompetitorPost.posted_at < end_utc)
    ).all()
    counts: dict[date, int] = defaultdict(int)
    for (posted_at,) in rows:
        if posted_at is None:
            continue
        counts[to_ist(posted_at).date()] += 1
    return {"days": [{"date": d.isoformat(), "posts": counts.get(d, 0)}
                      for d in _day_range(first_day, days)]}


def views_trend(s: Session, competitor_id: int, days: int = 30) -> dict:
    win = _window(s, competitor_id, days)
    if win is None:
        return {"days": []}
    first_day, _, start_utc, end_utc = win
    rows = s.execute(
        select(CompetitorPost.posted_at, CompetitorPost.views)
        .where(CompetitorPost.competitor_id == competitor_id,
               CompetitorPost.posted_at >= start_utc, CompetitorPost.posted_at < end_utc)
    ).all()
    totals: dict[date, int] = defaultdict(int)
    counts: dict[date, int] = defaultdict(int)
    for posted_at, views in rows:
        if posted_at is None:
            continue
        d = to_ist(posted_at).date()
        counts[d] += 1
        totals[d] += (views or 0)
    series = []
    for d in _day_range(first_day, days):
        n = counts.get(d, 0)
        series.append({"date": d.isoformat(), "total_views": totals.get(d, 0),
                        "avg_views": round(totals[d] / n, 1) if n else 0.0})
    return {"days": series}


def merchant_trend(s: Session, competitor_id: int, days: int = 30) -> dict:
    """Daily count per merchant, capped to the overall top N so a long-tail
    competitor doesn't explode the response — everything else collapses into
    "other" (has a resolved-but-uncommon merchant) or "unknown" (no merchant_key)."""
    win = _window(s, competitor_id, days)
    if win is None:
        return {"merchants": [], "days": []}
    first_day, _, start_utc, end_utc = win
    rows = s.execute(
        select(CompetitorPost.posted_at, NormalizedPost.primary_merchant_key)
        .join(NormalizedPost, NormalizedPost.source_id == CompetitorPost.id)
        .where(NormalizedPost.source_type == SourceType.COMPETITOR,
               CompetitorPost.competitor_id == competitor_id,
               CompetitorPost.posted_at >= start_utc, CompetitorPost.posted_at < end_utc)
    ).all()

    overall = Counter(mk for _, mk in rows if mk)
    top = [mk for mk, _ in overall.most_common(TOP_MERCHANTS_N)]
    top_set = set(top)
    has_other = len(overall) > len(top)
    has_unknown = any(mk is None for _, mk in rows)

    def bucket(mk: str | None) -> str:
        if mk is None:
            return "unknown"
        return mk if mk in top_set else "other"

    per_day: dict[date, Counter] = defaultdict(Counter)
    for posted_at, mk in rows:
        if posted_at is None:
            continue
        per_day[to_ist(posted_at).date()][bucket(mk)] += 1

    merchants = top + (["other"] if has_other else []) + (["unknown"] if has_unknown else [])
    series = [{"date": d.isoformat(), "counts": {m: per_day.get(d, Counter()).get(m, 0) for m in merchants}}
              for d in _day_range(first_day, days)]
    return {"merchants": merchants, "days": series}


def top_posts(s: Session, competitor_id: int, limit: int = 10) -> list[dict]:
    """Ranked list (not a trend) of this competitor's posts by views."""
    rows = s.execute(
        select(CompetitorPost.id, CompetitorPost.posted_at, CompetitorPost.views,
               CompetitorPost.forwards, CompetitorPost.reactions_total,
               CompetitorPost.text, CompetitorPost.links)
        .where(CompetitorPost.competitor_id == competitor_id)
        .order_by(CompetitorPost.views.desc().nullslast())
        .limit(limit)
    ).all()
    out = []
    for pid, posted_at, views, forwards, reactions_total, text, links in rows:
        out.append({
            "id": pid,
            "posted_at": to_ist(posted_at).isoformat() if posted_at else None,
            "views": views,
            "forwards": forwards,
            "reactions_total": reactions_total,
            "text_snippet": (text or "").strip().replace("\n", " ")[:TEXT_SNIPPET_LEN],
            "link": (links or [None])[0],
        })
    return out


def content_mix_trend(s: Session, competitor_id: int, days: int = 30) -> dict:
    """Daily loot_deal vs single_deal count — same classification as day.py's
    _post_type (is_multi_deal), reused rather than reinvented."""
    win = _window(s, competitor_id, days)
    if win is None:
        return {"days": []}
    first_day, _, start_utc, end_utc = win
    rows = s.execute(
        select(CompetitorPost.posted_at, NormalizedPost.is_multi_deal)
        .join(NormalizedPost, NormalizedPost.source_id == CompetitorPost.id)
        .where(NormalizedPost.source_type == SourceType.COMPETITOR,
               CompetitorPost.competitor_id == competitor_id,
               CompetitorPost.posted_at >= start_utc, CompetitorPost.posted_at < end_utc)
    ).all()
    per_day: dict[date, Counter] = defaultdict(Counter)
    for posted_at, multi in rows:
        if posted_at is None:
            continue
        per_day[to_ist(posted_at).date()][_post_type(multi)] += 1
    series = []
    for d in _day_range(first_day, days):
        c = per_day.get(d, Counter())
        series.append({"date": d.isoformat(), "loot_deal": c.get("loot_deal", 0),
                        "single_deal": c.get("single_deal", 0)})
    return {"days": series}


def media_text_trend(s: Session, competitor_id: int, days: int = 30) -> dict:
    win = _window(s, competitor_id, days)
    if win is None:
        return {"days": []}
    first_day, _, start_utc, end_utc = win
    rows = s.execute(
        select(CompetitorPost.posted_at, CompetitorPost.has_media)
        .where(CompetitorPost.competitor_id == competitor_id,
               CompetitorPost.posted_at >= start_utc, CompetitorPost.posted_at < end_utc)
    ).all()
    per_day: dict[date, Counter] = defaultdict(Counter)
    for posted_at, has_media in rows:
        if posted_at is None:
            continue
        per_day[to_ist(posted_at).date()]["media" if has_media else "text"] += 1
    series = []
    for d in _day_range(first_day, days):
        c = per_day.get(d, Counter())
        series.append({"date": d.isoformat(), "media": c.get("media", 0), "text": c.get("text", 0)})
    return {"days": series}


def link_usage_trend(s: Session, competitor_id: int, days: int = 30) -> dict:
    """Daily avg links-per-post, from NormalizedPost.num_links — the same source
    of truth avg_links (competitor_metrics.py) already uses, not a re-count of the
    raw CompetitorPost.links list."""
    win = _window(s, competitor_id, days)
    if win is None:
        return {"days": []}
    first_day, _, start_utc, end_utc = win
    rows = s.execute(
        select(CompetitorPost.posted_at, NormalizedPost.num_links)
        .join(NormalizedPost, NormalizedPost.source_id == CompetitorPost.id)
        .where(NormalizedPost.source_type == SourceType.COMPETITOR,
               CompetitorPost.competitor_id == competitor_id,
               CompetitorPost.posted_at >= start_utc, CompetitorPost.posted_at < end_utc)
    ).all()
    totals: dict[date, int] = defaultdict(int)
    counts: dict[date, int] = defaultdict(int)
    for posted_at, num_links in rows:
        if posted_at is None:
            continue
        d = to_ist(posted_at).date()
        totals[d] += (num_links or 0)
        counts[d] += 1
    series = []
    for d in _day_range(first_day, days):
        n = counts.get(d, 0)
        series.append({"date": d.isoformat(), "avg_links": round(totals[d] / n, 2) if n else 0.0})
    return {"days": series}


def caption_length_distribution(s: Session, competitor_id: int) -> dict:
    """Histogram (not a trend) of caption/text length in fixed ranges."""
    rows = s.execute(
        select(CompetitorPost.text).where(CompetitorPost.competitor_id == competitor_id)
    ).all()
    counts = [0] * len(LENGTH_BUCKETS)
    for (text,) in rows:
        n = len(text or "")
        for i, (lo, hi) in enumerate(LENGTH_BUCKETS):
            if n >= lo and (hi is None or n < hi):
                counts[i] += 1
                break
    buckets = [{"range": f"{lo}-{hi}" if hi is not None else f"{lo}+", "count": c}
               for (lo, hi), c in zip(LENGTH_BUCKETS, counts)]
    return {"buckets": buckets}


def posting_consistency(s: Session, competitor_id: int, days: int = 30) -> dict:
    """Variance/stdev of daily post counts over the window — reuses posting_trend's
    data instead of re-querying."""
    daily_counts = [d["posts"] for d in posting_trend(s, competitor_id, days)["days"]]
    if len(daily_counts) < 2:
        mean = float(daily_counts[0]) if daily_counts else 0.0
        return {"daily_counts": daily_counts, "mean": mean, "stdev": 0.0, "variance": 0.0}
    return {
        "daily_counts": daily_counts,
        "mean": round(statistics.fmean(daily_counts), 2),
        "stdev": round(statistics.pstdev(daily_counts), 2),
        "variance": round(statistics.pvariance(daily_counts), 2),
    }


def all_trends(s: Session, competitor_id: int, days: int = 30) -> dict:
    """Everything above, in one payload — what the /trends route calls."""
    return {
        "posting_trend": posting_trend(s, competitor_id, days),
        "views_trend": views_trend(s, competitor_id, days),
        "merchant_trend": merchant_trend(s, competitor_id, days),
        "top_posts": top_posts(s, competitor_id, limit=10),
        "content_mix_trend": content_mix_trend(s, competitor_id, days),
        "media_text_trend": media_text_trend(s, competitor_id, days),
        "link_usage_trend": link_usage_trend(s, competitor_id, days),
        "caption_length_distribution": caption_length_distribution(s, competitor_id),
        "posting_consistency": posting_consistency(s, competitor_id, days),
    }
