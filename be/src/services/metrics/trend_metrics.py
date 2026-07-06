"""Period-over-period trend aggregation for the Reasoning Engine.

Loads owned-post facts once, then computes aggregates for arbitrary time
windows. Volume / mix / style shifts use the posting DATE (robust, not
view-dependent). Engagement shifts use MATURITY-MATCHED posts (both periods aged
the same amount) to avoid the cumulative-view recency bias — comparing a fresh
post's views to a months-old post's views would be meaningless.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import Post
from src.db.models_classification import PostClassification, PostTypeCluster
from src.db.models_normalization import NormalizedPost, SourceType


@dataclass
class TrendFact:
    posted_at: datetime
    views: int | None
    cluster: str | None
    merchant_key: str | None
    has_cta: bool
    has_media: bool


def load_owned_facts(s: Session) -> list[TrendFact]:
    np_rows = s.execute(
        select(NormalizedPost.source_id, NormalizedPost.cta_texts,
               NormalizedPost.primary_merchant_key, NormalizedPost.id)
        .where(NormalizedPost.source_type == SourceType.OWNED)
    ).all()
    post_meta = {
        pid: (posted_at, views, media)
        for pid, posted_at, views, media in s.execute(
            select(Post.id, Post.posted_at, Post.views, Post.has_media)
        ).all()
    }
    npids = [r[3] for r in np_rows]
    clusters = {}
    if npids:
        for npid, desc in s.execute(
            select(PostClassification.normalized_post_id, PostTypeCluster.descriptor)
            .join(PostTypeCluster, PostTypeCluster.id == PostClassification.cluster_id)
            .where(PostClassification.normalized_post_id.in_(npids))
        ).all():
            clusters[npid] = desc

    facts = []
    for src_id, cta, mkey, npid in np_rows:
        meta = post_meta.get(src_id)
        if not meta or meta[0] is None:
            continue
        posted_at, views, media = meta
        pa = posted_at if posted_at.tzinfo else posted_at.replace(tzinfo=timezone.utc)
        facts.append(TrendFact(
            posted_at=pa, views=views, cluster=clusters.get(npid),
            merchant_key=mkey, has_cta=bool(cta), has_media=bool(media),
        ))
    return facts


def in_posting_window(facts: list[TrendFact], start: datetime, end: datetime) -> list[TrendFact]:
    return [f for f in facts if start <= f.posted_at < end]


def matured_window(facts: list[TrendFact], now: datetime, age_lo_days: int, age_hi_days: int):
    """Posts whose age is in [age_lo, age_hi) days — both engagement periods use
    equal maturity so cumulative-view totals are comparable."""
    out = []
    for f in facts:
        age = (now - f.posted_at).total_seconds() / 86400.0
        if age_lo_days <= age < age_hi_days:
            out.append(f)
    return out


def avg_views_per_day(facts: list[TrendFact], now: datetime) -> tuple[float | None, int]:
    vals = []
    for f in facts:
        if f.views is None:
            continue
        age = max((now - f.posted_at).total_seconds() / 86400.0, 1.0)
        vals.append(f.views / age)
    return (round(statistics.fmean(vals), 3) if vals else None, len(vals))


def posts_per_day(facts: list[TrendFact], span_days: int) -> float:
    return round(len(facts) / span_days, 3) if span_days else 0.0


def share_map(facts: list[TrendFact], key) -> dict[str, float]:
    counter = Counter(key(f) for f in facts if key(f))
    total = sum(counter.values()) or 1
    return {k: v / total for k, v in counter.items()}


def rate(facts: list[TrendFact], pred) -> float | None:
    return round(sum(1 for f in facts if pred(f)) / len(facts), 3) if facts else None
