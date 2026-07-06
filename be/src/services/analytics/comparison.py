"""Your channel vs competitors — comprehensive comparison using stored profiles + benchmarks.

Surfaces every dimension that the Competitor Intelligence engine has already
computed: style metrics (CTA, coupon, multi-deal, media, emoji rates), deal-mix
distributions, weekday/hourly timing, and per-dimension benchmark deltas.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.services.analytics.periods import IST
from src.db.models import Post
from src.db.models_normalization import NormalizedPost, SourceType
from src.db.models_learning import ChannelStyleProfile, PostTypePerformance, LEARNING_VERSION
from src.db.models_competitor_intel import (
    CompetitorProfile,
    CompetitorBenchmark,
    CompetitorSignal,
    COMPETITOR_INTEL_VERSION,
)

MIN_POSTS = 10
UNAVAILABLE = ["reactions", "forwards", "reach", "engagement_rate"]
_UNAVAILABLE_NOTE = (
    "Reactions, forwards, reach and engagement-rate need channel admin "
    "rights (your channel) or a bot in the channel; competitor data is the "
    "public t.me/s view count only. Shown as unavailable, never estimated."
)
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

STYLE_METRICS = [
    "avg_text_len", "emoji_rate", "cta_rate", "coupon_rate", "multi_deal_rate",
    "hashtag_rate", "avg_links", "media_rate",
]


def compare(s: Session, max_competitors: int = 6) -> dict:
    entities = []

    # ------------------------------------------------------------------ #
    # Owned entity
    # ------------------------------------------------------------------ #
    owned_rows = s.execute(
        select(Post.posted_at, Post.views)
        .join(NormalizedPost, NormalizedPost.source_id == Post.id)
        .where(NormalizedPost.source_type == SourceType.OWNED, Post.posted_at.isnot(None))
    ).all()

    owned_dates = [d for d, _ in owned_rows if d]
    if len(owned_dates) < MIN_POSTS:
        return {
            "entities": [],
            "benchmarks": [],
            "signals": [],
            "unavailable": UNAVAILABLE,
            "note": "Not enough owned posts collected yet.",
            "metrics": STYLE_METRICS + ["posts_per_day", "avg_views_per_post"],
        }

    owned_views = [v for _, v in owned_rows if v is not None]
    span_days = max((max(owned_dates) - min(owned_dates)).days, 0) + 1
    hours = Counter(d.astimezone(IST).hour for d in owned_dates)
    wd_counter = Counter(d.weekday() for d in owned_dates)

    owned: dict = {
        "name": "You (owned)",
        "is_owned": True,
        "posts": len(owned_dates),
        "window_days": span_days,
        "avg_views_per_post": round(statistics.fmean(owned_views)) if owned_views else None,
        "posts_per_day": round(len(owned_dates) / span_days, 2),
        "posts_per_hour_ist": [hours.get(h, 0) for h in range(24)],
        "weekday_distribution": {day: wd_counter.get(i, 0) for i, day in enumerate(WEEKDAYS)},
        "similarity_to_us": 1.0,
        "reactions": None,
        "forwards": None,
        "reach": None,
        "engagement_rate": None,
    }

    style = s.scalar(
        select(ChannelStyleProfile).where(ChannelStyleProfile.learning_version == LEARNING_VERSION)
    )
    if style:
        owned["avg_text_len"] = style.avg_caption_len
        owned["emoji_rate"] = style.avg_emojis
        owned["cta_rate"] = style.cta_rate
        owned["coupon_rate"] = style.coupon_rate
        owned["multi_deal_rate"] = style.multi_deal_rate
        owned["hashtag_rate"] = style.hashtag_rate
        owned["avg_links"] = style.avg_links
        owned["media_rate"] = style.media_rate
        owned["top_hours_ist"] = [h for h, _ in (style.top_hours_ist or [])]
        owned["posting_consistency"] = style.posting_consistency

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

    entities.append(owned)

    # ------------------------------------------------------------------ #
    # Competitor entities
    # ------------------------------------------------------------------ #
    profiles = s.scalars(
        select(CompetitorProfile)
        .where(CompetitorProfile.intel_version == COMPETITOR_INTEL_VERSION)
        .order_by(CompetitorProfile.post_count.desc())
    ).all()

    # benchmarks grouped by competitor_id
    bench_rows = s.scalars(
        select(CompetitorBenchmark)
        .where(CompetitorBenchmark.intel_version == COMPETITOR_INTEL_VERSION)
    ).all()
    benchmarks_by_comp: dict[int, list[dict]] = defaultdict(list)
    for b in bench_rows:
        benchmarks_by_comp[b.competitor_id].append({
            "dimension": b.dimension,
            "owned_value": b.owned_value,
            "competitor_value": b.competitor_value,
            "delta": b.delta,
        })

    # signals
    signals = [
        {
            "type": sig.signal_type,
            "competitor": sig.username,
            "kind": sig.kind,
            "description": sig.description,
            "confidence": sig.confidence,
        }
        for sig in s.scalars(
            select(CompetitorSignal)
            .where(CompetitorSignal.intel_version == COMPETITOR_INTEL_VERSION)
            .order_by(CompetitorSignal.confidence.desc())
        ).all()
    ]

    for cp in profiles[:max_competitors]:
        ent: dict = {
            "name": cp.username,
            "is_owned": False,
            "posts": cp.post_count,
            "window_days": cp.span_days,
            "avg_views_per_post": cp.avg_views,
            "posts_per_day": cp.posts_per_day,
            "avg_text_len": cp.avg_text_len,
            "emoji_rate": cp.emoji_rate,
            "cta_rate": cp.cta_rate,
            "coupon_rate": cp.coupon_rate,
            "multi_deal_rate": cp.multi_deal_rate,
            "hashtag_rate": cp.hashtag_rate,
            "avg_links": cp.avg_links,
            "media_rate": cp.media_rate,
            "top_hour_ist": cp.top_posting_hour_ist,
            "weekday_distribution": cp.weekday_distribution,
            "hour_distribution_ist": cp.hour_distribution_ist,
            "deal_mix": cp.deal_mix,
            "merchant_mix": cp.merchant_mix,
            "merchant_coverage": cp.merchant_coverage,
            "similarity_to_us": cp.similarity_to_owned,
            "confidence": cp.confidence,
            "benchmarks": benchmarks_by_comp.get(cp.competitor_id, []),
            "reactions": None,
            "forwards": None,
            "reach": None,
            "engagement_rate": None,
        }
        if cp.hour_distribution_ist:
            ent["posts_per_hour_ist"] = [cp.hour_distribution_ist.get(str(h), 0) for h in range(24)]
        else:
            ent["posts_per_hour_ist"] = [0] * 24
        entities.append(ent)

    return {
        "entities": entities,
        "signals": signals,
        "unavailable": UNAVAILABLE,
        "note": _UNAVAILABLE_NOTE,
        "metrics": STYLE_METRICS + ["posts_per_day", "avg_views_per_post"],
    }
