"""Your channel vs competitors — with timeline-aware comparison.

Surfaces every dimension the Competitor Intelligence engine computes (style
metrics, deal-mix, benchmarks) AND the observation window each entity is based
on. A ``window_days`` param lets you compare within a specific recent period;
pre-computed fields (deal_mix, style) carry a note when the period differs.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.services.analytics.periods import WEEKDAYS, to_ist
from src.db.models import Competitor, CompetitorPost, Post
from src.db.models_normalization import NormalizedPost, SourceType
from src.db.models_learning import ChannelStyleProfile, PostTypePerformance, LEARNING_VERSION
from src.db.models_competitor_intel import CompetitorProfile
from src.services.intelligence.competitor import latest_benchmarks, latest_profiles

MIN_POSTS = 10
# avg_views trust gate (see _basic_stats): need this many real view captures, and the
# mean can't exceed the median by more than this ratio (kills single parse-error spikes).
_MIN_VIEW_SAMPLE = 8
_VIEW_OUTLIER_RATIO = 20
# A real channel doesn't AVERAGE under this many views — an avg below it means the
# scraper captured placeholders, not real counts (e.g. india_online_deal "avg 2").
_MIN_PLAUSIBLE_AVG = 5
# avg_views above this multiple of the channel's subscriber count is impossible (a
# mis-parsed view number), so the avg is flagged unreliable — allows for forwards/virality.
_VIEWS_VS_SUBS_CEIL = 3
UNAVAILABLE = ["reach", "engagement_rate"]
_UNAVAILABLE_NOTE = (
    "Reach and engagement-rate need channel admin rights; competitor data is the "
    "public t.me/s view count only. Shown as unavailable, never estimated."
)

STYLE_METRICS = [
    "avg_text_len", "emoji_rate", "cta_rate", "coupon_rate", "multi_deal_rate",
    "hashtag_rate", "avg_links", "media_rate",
]


def _fmt_date(dt: datetime | None) -> str | None:
    return to_ist(dt).isoformat() if dt else None


def _tenure_label(first: datetime | None, last: datetime | None, n: int, window_filter: int | None = None) -> str | None:
    if not first or not last or not n:
        return None
    span = max((last - first).days, 0) + 1
    f = to_ist(first).strftime("%b %d")
    l = to_ist(last).strftime("%b %d, %Y")
    if window_filter:
        return f"Last {window_filter}d ({f}\u2192{l}) \u00b7 {n:,} posts"
    return f"{span}d window ({f}\u2192{l}) \u00b7 n={n:,} posts"


def _basic_stats(dated_views: list[tuple[datetime, int | None]]) -> dict | None:
    """Compute basic post stats from a list of (posted_at, views) tuples.
    Returns None when under MIN_POSTS."""
    dates = [d for d, _ in dated_views if d]
    if len(dates) < MIN_POSTS:
        return None
    views = [v for _, v in dated_views if v is not None]
    span_days = max((max(dates) - min(dates)).days, 0) + 1
    hours = Counter(to_ist(d).hour for d in dates)
    wd_counter = Counter(to_ist(d).weekday() for d in dates)
    avg_views = round(statistics.fmean(views)) if views else None
    med_views = round(statistics.median(views)) if views else None
    # Whether avg_views can be TRUSTED. Some channels scrape with no real view counts
    # (all placeholders ~1 -> a fake "avg 2") or one parse-error outlier that drags the
    # mean to nonsense (a single 327,233 -> a fake "avg 16k"). The median is robust to
    # both, so we gate on: enough real captures, a median above the placeholder floor,
    # and a mean not wildly above the median.
    avg_views_reliable = bool(
        views and len(views) >= _MIN_VIEW_SAMPLE
        and med_views and med_views > 1
        and avg_views is not None and avg_views >= _MIN_PLAUSIBLE_AVG
        and avg_views <= _VIEW_OUTLIER_RATIO * med_views)
    return {
        "posts": len(dates),
        "window_days": span_days,
        "avg_views_per_post": avg_views,
        "median_views": med_views,
        "avg_views_reliable": avg_views_reliable,
        "views_sample": len(views),
        "posts_per_day": round(len(dates) / span_days, 2),
        "posts_per_hour_ist": [hours.get(h, 0) for h in range(24)],
        "weekday_distribution": {day: wd_counter.get(i, 0) for i, day in enumerate(WEEKDAYS)},
        "first_posted_at": _fmt_date(min(dates)),
        "last_posted_at": _fmt_date(max(dates)),
        "tenure_label": _tenure_label(min(dates), max(dates), len(dates)),
    }


def _view_reliability_by_comp(s: Session) -> dict[int, dict]:
    """Per-competitor avg_views trust, from raw CompetitorPost views in one query.
    Reliable = enough real captures, a median above the placeholder floor (>1), and a
    mean not wildly above the median (no single parse-error spike). Same test as
    _basic_stats, but computed for the profile-based (full-window) dashboard path."""
    rows = s.execute(
        select(CompetitorPost.competitor_id, CompetitorPost.views)
        .where(CompetitorPost.views.isnot(None))
    ).all()
    by_comp: dict[int, list[int]] = defaultdict(list)
    for cid, v in rows:
        by_comp[cid].append(v)
    out: dict[int, dict] = {}
    for cid, views in by_comp.items():
        med = round(statistics.median(views))
        avg = statistics.fmean(views)
        reliable = (len(views) >= _MIN_VIEW_SAMPLE and med > 1 and avg >= _MIN_PLAUSIBLE_AVG
                    and avg <= _VIEW_OUTLIER_RATIO * med)
        out[cid] = {"median": med, "sample": len(views), "reliable": reliable}
    return out


def _entity_name(prefix: str, cp: CompetitorProfile | None, cid: int) -> str:
    if cp:
        return cp.username
    return prefix


_SUBSCRIBER_SUFFIXES = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def _parse_subscribers(text: str | None) -> int | None:
    """Parse the public t.me/s subscriber count string (e.g. "1.2K", "45,231",
    "980") into an int. Not guaranteed numeric/parseable — returns None rather
    than guessing when the format doesn't match, per this project's convention
    of showing unavailable data as unavailable (see UNAVAILABLE/_UNAVAILABLE_NOTE)."""
    if not text:
        return None
    t = text.strip().replace(",", "")
    if not t:
        return None
    multiplier = 1
    suffix = t[-1].upper()
    if suffix in _SUBSCRIBER_SUFFIXES:
        multiplier = _SUBSCRIBER_SUFFIXES[suffix]
        t = t[:-1]
    try:
        value = float(t)
    except ValueError:
        return None
    return int(round(value * multiplier))


def compare(s: Session, max_competitors: int = 6, window_days: int | None = None) -> dict:
    cutoff = None
    if window_days and window_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    entities = []

    # ------------------------------------------------------------------ #
    # Owned entity
    # ------------------------------------------------------------------ #
    owned_q = (
        select(Post.posted_at, Post.views, Post.reactions_total, Post.forwards)
        .join(NormalizedPost, NormalizedPost.source_id == Post.id)
        .where(NormalizedPost.source_type == SourceType.OWNED, Post.posted_at.isnot(None))
    )
    if cutoff:
        owned_q = owned_q.where(Post.posted_at >= cutoff)
    owned_rows = s.execute(owned_q).all()

    owned_dates = [d for d, _, _, _ in owned_rows if d]
    # windowed views only need a couple of owned posts to compare; the full ("All")
    # view needs MIN_POSTS. NOTE: the threshold must be computed on its own line —
    # inlining it as `len < min(...) if cutoff else MIN_POSTS` mis-parses to
    # `(len < min(...)) if cutoff else MIN_POSTS`, so the no-window branch returned a
    # truthy constant and the "All" tab always short-circuited to empty.
    min_owned = min(MIN_POSTS, 2) if cutoff else MIN_POSTS
    if len(owned_dates) < min_owned:
        return {
            "entities": [],
            "unavailable": UNAVAILABLE,
            "note": "Not enough owned posts in the selected window." if cutoff else "Not enough owned posts collected yet.",
            "metrics": STYLE_METRICS + ["posts_per_day", "avg_views_per_post"],
            "applied_window": window_days,
        }

    stats = _basic_stats([(d, v) for d, v, _, _ in owned_rows])
    owned_reactions = [r for _, _, r, _ in owned_rows if r is not None]
    owned_forwards = [f for _, _, _, f in owned_rows if f is not None]
    owned_avg_reactions = round(statistics.fmean(owned_reactions)) if owned_reactions else None
    owned_avg_forwards = round(statistics.fmean(owned_forwards)) if owned_forwards else None
    owned: dict = {
        "name": "You (owned)",
        "is_owned": True,
        "is_window_filtered": bool(cutoff),
    }
    if stats:
        owned.update(stats)
    owned.update({
        "similarity_to_us": 1.0,
        "reactions": owned_avg_reactions, "forwards": owned_avg_forwards,
        "reach": None, "engagement_rate": None,
    })

    # style profile (full-window, always)
    style = s.scalar(select(ChannelStyleProfile).where(ChannelStyleProfile.learning_version == LEARNING_VERSION))
    if style:
        owned.update({
            "avg_text_len": style.avg_caption_len,
            "emoji_rate": style.avg_emojis,
            "cta_rate": style.cta_rate,
            "coupon_rate": style.coupon_rate,
            "multi_deal_rate": style.multi_deal_rate,
            "hashtag_rate": style.hashtag_rate,
            "avg_links": style.avg_links,
            "media_rate": style.media_rate,
            "top_hours_ist": [h for h, _ in (style.top_hours_ist or [])],
            "posting_consistency": style.posting_consistency,
        })
        if cutoff:
            owned["style_tenure_note"] = "Full observation window"

    # deal mix (full-window, always)
    ptp_rows = s.scalars(
        select(PostTypePerformance)
        .where(PostTypePerformance.learning_version == LEARNING_VERSION)
        .order_by(PostTypePerformance.rank_by_views_per_day)
    ).all()
    if ptp_rows:
        owned["deal_mix"] = {p.post_type: p.share for p in ptp_rows}
        owned["deal_mix_detail"] = {
            p.post_type: {"share": p.share, "avg_views_per_day": p.avg_views_per_day, "posts": p.post_count}
            for p in ptp_rows
        }
        if cutoff:
            owned["deal_mix_note"] = "Full observation window"

    entities.append(owned)

    # ------------------------------------------------------------------ #
    # Competitor entities
    # ------------------------------------------------------------------ #
    # Pre-fetch benchmarks grouped by competitor_id (latest snapshot per dimension)
    bench_rows = latest_benchmarks(s)
    benchmarks_by_comp: dict[int, list[dict]] = defaultdict(list)
    for b in bench_rows:
        benchmarks_by_comp[b.competitor_id].append({
            "dimension": b.dimension, "owned_value": b.owned_value,
            "competitor_value": b.competitor_value, "delta": b.delta,
        })

    # Pre-fetch subscriber counts (public t.me/s scrape, not guaranteed numeric)
    subscribers_by_comp: dict[int, int | None] = {
        c.id: _parse_subscribers(c.subscribers_text)
        for c in s.scalars(select(Competitor)).all()
    }

    if cutoff:
        # ------------------------------------------------------------------ #
        # Window-filtered mode: re-query raw CompetitorPost rows
        # ------------------------------------------------------------------ #
        raw = s.execute(
            select(CompetitorPost.competitor_id, CompetitorPost.posted_at, CompetitorPost.views)
            .where(CompetitorPost.posted_at.isnot(None), CompetitorPost.posted_at >= cutoff)
        ).all()
        comp_posts: dict[int, list[tuple[datetime, int | None]]] = defaultdict(list)
        for cid, dt, v in raw:
            if dt:
                comp_posts[cid].append((dt, v))

        # profile lookup (latest snapshot per competitor)
        all_profiles = {p.competitor_id: p for p in latest_profiles(s)}

        # sort by post count
        sorted_comps = sorted(comp_posts.items(), key=lambda x: len(x[1]), reverse=True)

        for cid, dated_views in sorted_comps[:max_competitors]:
            bs = _basic_stats(dated_views)
            if bs is None:
                continue
            cp = all_profiles.get(cid)
            ent: dict = {
                "id": cid,
                "name": cp.username if cp else next(
                    (c.username for c in s.scalars(select(Competitor).where(Competitor.id == cid)).all() if c.username),
                    f"comp{cid}",
                ),
                "is_owned": False,
                "is_window_filtered": True,
                "subscribers": subscribers_by_comp.get(cid),
            }
            ent.update(bs)
            # override tenure label to reflect the window filter
            if bs.get("first_posted_at") and bs.get("last_posted_at"):
                first = datetime.fromisoformat(bs["first_posted_at"])
                last = datetime.fromisoformat(bs["last_posted_at"])
                ent["tenure_label"] = _tenure_label(first, last, bs["posts"], window_days)
            # attach pre-computed full-window data
            if cp:
                ent.update({
                    "avg_text_len": cp.avg_text_len, "emoji_rate": cp.emoji_rate,
                    "cta_rate": cp.cta_rate, "coupon_rate": cp.coupon_rate,
                    "multi_deal_rate": cp.multi_deal_rate, "media_rate": cp.media_rate,
                    "hashtag_rate": cp.hashtag_rate, "avg_links": cp.avg_links,
                    "deal_mix": cp.deal_mix, "merchant_mix": cp.merchant_mix,
                    "merchant_coverage": cp.merchant_coverage,
                    "similarity_to_us": cp.similarity_to_owned,
                    "confidence": cp.confidence,
                    "benchmarks": benchmarks_by_comp.get(cid, []),
                    "style_tenure_note": "Full observation window",
                    "deal_mix_note": "Full observation window",
                })
            ent.update({
                "reactions": None, "forwards": None, "reach": None, "engagement_rate": None,
            })
            entities.append(ent)
    else:
        # ------------------------------------------------------------------ #
        # Full-window mode: use pre-computed CompetitorProfile (latest snapshot per competitor)
        # ------------------------------------------------------------------ #
        profiles = sorted(latest_profiles(s), key=lambda p: -(p.post_count or 0))

        for cp in profiles[:max_competitors]:
            ent: dict = {
                "id": cp.competitor_id,
                "name": cp.username, "is_owned": False, "is_window_filtered": False,
                "subscribers": subscribers_by_comp.get(cp.competitor_id),
                "posts": cp.post_count, "window_days": cp.span_days,
                "avg_views_per_post": cp.avg_views, "posts_per_day": cp.posts_per_day,
                "avg_text_len": cp.avg_text_len, "emoji_rate": cp.emoji_rate,
                "cta_rate": cp.cta_rate, "coupon_rate": cp.coupon_rate,
                "multi_deal_rate": cp.multi_deal_rate, "hashtag_rate": cp.hashtag_rate,
                "avg_links": cp.avg_links, "media_rate": cp.media_rate,
                "top_hour_ist": cp.top_posting_hour_ist,
                "weekday_distribution": cp.weekday_distribution,
                "hour_distribution_ist": cp.hour_distribution_ist,
                "deal_mix": cp.deal_mix, "merchant_mix": cp.merchant_mix,
                "merchant_coverage": cp.merchant_coverage,
                "similarity_to_us": cp.similarity_to_owned, "confidence": cp.confidence,
                "benchmarks": benchmarks_by_comp.get(cp.competitor_id, []),
                "first_posted_at": _fmt_date(cp.first_posted_at),
                "last_posted_at": _fmt_date(cp.last_posted_at),
                "tenure_label": _tenure_label(cp.first_posted_at, cp.last_posted_at, cp.post_count or 0),
                "reactions": None, "forwards": None, "reach": None, "engagement_rate": None,
            }
            if cp.hour_distribution_ist:
                ent["posts_per_hour_ist"] = [cp.hour_distribution_ist.get(str(h), 0) for h in range(24)]
            else:
                ent["posts_per_hour_ist"] = [0] * 24
            entities.append(ent)

    # Flag entities whose observation window is wildly different from owned's —
    # posts_per_day/avg_views_per_post are computed over each entity's OWN window
    # independently, so comparing e.g. owned's 365-day history against a
    # competitor tracked for only 20 days looks apples-to-apples but isn't. Never
    # silently normalize this (we can't fabricate the missing history); flag it
    # so the UI can caveat instead of implying a fair comparison.
    owned_window_days = owned.get("window_days")
    for ent in entities:
        if ent.get("is_owned"):
            continue
        cwd = ent.get("window_days")
        if owned_window_days and cwd:
            ratio = cwd / owned_window_days
            ent["window_mismatch"] = ratio < 0.5 or ratio > 2.0
        else:
            ent["window_mismatch"] = None

    # avg_views trust flag per competitor — the profile-based branch carries only the
    # MEAN, which lies when views are placeholders (all ~1 -> "avg 2") or a parse-error
    # spike (one 327,233 -> "avg 16k"). Compute the median from raw posts once and gate.
    _rel = _view_reliability_by_comp(s)
    for ent in entities:
        if ent.get("is_owned"):
            continue
        r = _rel.get(ent.get("id"))
        if ent.get("median_views") is None:
            ent["median_views"] = r["median"] if r else None
        if ent.get("views_sample") is None:
            ent["views_sample"] = r["sample"] if r else 0
        reliable = bool(r and r["reliable"]) if ent.get("avg_views_reliable") is None \
            else ent["avg_views_reliable"]
        # Plausibility ceiling: a post cannot AVERAGE several times the channel's own
        # subscriber base — views far above subscribers means the scraper mis-parsed the
        # number (e.g. a 20-post channel "averaging" 327,233 views). Flag as unreliable.
        avg, subs = ent.get("avg_views_per_post"), ent.get("subscribers")
        if reliable and subs and avg and avg > _VIEWS_VS_SUBS_CEIL * subs:
            reliable = False
        ent["avg_views_reliable"] = reliable

    return {
        "entities": entities,
        "unavailable": UNAVAILABLE,
        "note": _UNAVAILABLE_NOTE,
        "metrics": STYLE_METRICS + ["posts_per_day", "avg_views_per_post"],
        "applied_window": window_days,
    }
