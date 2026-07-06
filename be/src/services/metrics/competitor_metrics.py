"""Raw channel-behaviour aggregation for competitor intelligence.

Computes the SAME behaviour metrics for our owned channel and for each
competitor, so they can be compared apples-to-apples. Reads Phase-2 normalized
entities + Phase-3 clusters + the raw source rows (text length, media, views,
timestamps). Assigns no meaning and computes no scores.

Honest limits: t.me/s exposes rounded, cumulative views and NOT forwards/
reactions for competitors — those are simply absent, never invented. Most links
are unresolved shortlinks, so merchant_mix covers only resolved domains and a
coverage fraction is reported alongside it.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import CompetitorPost, Post
from src.db.models_classification import PostClassification, PostTypeCluster
from src.db.models_normalization import (
    ExtractedLink,
    NormalizedPost,
    SourceType,
)

IST = timezone(timedelta(hours=5, minutes=30))


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@dataclass
class PostFeature:
    posted_at: datetime | None
    text_len: int
    has_media: bool
    views: int | None
    num_links: int
    has_coupon: bool
    is_multi_deal: bool
    emoji_count: int
    hashtag_count: int
    has_cta: bool
    merchant_key: str | None
    cluster: str | None
    known_link_count: int
    total_link_count: int


@dataclass
class ChannelBehaviour:
    label: str
    features: list[PostFeature] = field(default_factory=list)

    def summary(self) -> dict:
        f = self.features
        n = len(f)
        dated = [_aware(p.posted_at) for p in f if p.posted_at]
        span_days = None
        posts_per_day = None
        if dated:
            span_days = max((max(dated) - min(dated)).days, 0) + 1
            posts_per_day = round(n / span_days, 3)
        views = [p.views for p in f if p.views is not None]

        # timing in IST
        hours = Counter()
        weekdays = Counter()
        for d in dated:
            ist = d.astimezone(IST)
            hours[ist.hour] += 1
            weekdays[ist.strftime("%a")] += 1
        top_hour = hours.most_common(1)[0][0] if hours else None

        # mixes
        deal_mix = Counter(p.cluster for p in f if p.cluster)
        merchant_mix = Counter(p.merchant_key for p in f if p.merchant_key)
        total_links = sum(p.total_link_count for p in f)
        known_links = sum(p.known_link_count for p in f)
        coverage = round(known_links / total_links, 3) if total_links else 0.0

        def rate(pred) -> float | None:
            return round(sum(1 for p in f if pred(p)) / n, 3) if n else None

        def mean(vals) -> float | None:
            return round(statistics.fmean(vals), 3) if vals else None

        return {
            "label": self.label,
            "post_count": n,
            "span_days": span_days,
            "posts_per_day": posts_per_day,
            "first_posted_at": min(dated) if dated else None,
            "last_posted_at": max(dated) if dated else None,
            "avg_text_len": mean([p.text_len for p in f]),
            "emoji_rate": mean([p.emoji_count for p in f]),
            "hashtag_rate": mean([p.hashtag_count for p in f]),
            "cta_rate": rate(lambda p: p.has_cta),
            "coupon_rate": rate(lambda p: p.has_coupon),
            "multi_deal_rate": rate(lambda p: p.is_multi_deal),
            "avg_links": mean([p.num_links for p in f]),
            "media_rate": rate(lambda p: p.has_media),
            "avg_views": mean(views),
            "views_sample_size": len(views),
            "top_posting_hour_ist": top_hour,
            "hour_distribution_ist": dict(sorted(hours.items())) or None,
            "weekday_distribution": dict(weekdays) or None,
            "deal_mix": dict(deal_mix) or None,
            "merchant_mix": dict(merchant_mix) or None,
            "merchant_coverage": coverage,
        }


def _feature_maps(s: Session, source_type: str, source_ids: list[int]):
    """cluster + resolved-link counts for a set of normalized_post ids."""
    if not source_ids:
        return {}, {}, {}
    # normalized posts of this source_type indexed by source_id
    np_rows = s.execute(
        select(NormalizedPost.id, NormalizedPost.source_id)
        .where(
            NormalizedPost.source_type == source_type,
            NormalizedPost.source_id.in_(source_ids),
        )
    ).all()
    npid_to_src = {npid: src for npid, src in np_rows}
    npids = list(npid_to_src.keys())

    clusters = {}
    if npids:
        for npid, desc in s.execute(
            select(PostClassification.normalized_post_id, PostTypeCluster.descriptor)
            .join(PostTypeCluster, PostTypeCluster.id == PostClassification.cluster_id)
            .where(PostClassification.normalized_post_id.in_(npids))
        ).all():
            clusters[npid_to_src[npid]] = desc

    # link counts (total + resolved-merchant) per source post
    total_links: dict[int, int] = {}
    known_links: dict[int, int] = {}
    if npids:
        for npid, mkey in s.execute(
            select(ExtractedLink.normalized_post_id, ExtractedLink.merchant_key)
            .where(ExtractedLink.normalized_post_id.in_(npids))
        ).all():
            src = npid_to_src[npid]
            total_links[src] = total_links.get(src, 0) + 1
            if mkey:
                known_links[src] = known_links.get(src, 0) + 1
    return clusters, total_links, known_links


def compute_owned_behaviour(s: Session) -> ChannelBehaviour:
    ch = ChannelBehaviour(label="owned")
    np_rows = s.execute(
        select(
            NormalizedPost.source_id, NormalizedPost.num_links, NormalizedPost.has_coupon,
            NormalizedPost.is_multi_deal, NormalizedPost.emojis, NormalizedPost.hashtags,
            NormalizedPost.cta_texts, NormalizedPost.primary_merchant_key,
        ).where(NormalizedPost.source_type == SourceType.OWNED)
    ).all()
    src_ids = [r[0] for r in np_rows]
    post_rows = {
        pid: (posted_at, tlen, media, views)
        for pid, posted_at, tlen, media, views in s.execute(
            select(Post.id, Post.posted_at, _len(Post.text), Post.has_media, Post.views)
        ).all()
    }
    clusters, total_links, known_links = _feature_maps(s, SourceType.OWNED, src_ids)
    for src_id, num_links, has_coupon, multi, emojis, hashtags, cta, mkey in np_rows:
        meta = post_rows.get(src_id)
        if not meta:
            continue
        posted_at, tlen, media, views = meta
        ch.features.append(PostFeature(
            posted_at=posted_at, text_len=tlen or 0, has_media=bool(media), views=views,
            num_links=num_links, has_coupon=has_coupon, is_multi_deal=multi,
            emoji_count=len(emojis or []), hashtag_count=len(hashtags or []),
            has_cta=bool(cta), merchant_key=mkey, cluster=clusters.get(src_id),
            known_link_count=known_links.get(src_id, 0),
            total_link_count=total_links.get(src_id, 0),
        ))
    return ch


def compute_competitor_behaviours(s: Session):
    """Return (dict[competitor_id -> ChannelBehaviour], dict[competitor_id -> username])."""
    np_rows = s.execute(
        select(
            NormalizedPost.source_id, NormalizedPost.num_links, NormalizedPost.has_coupon,
            NormalizedPost.is_multi_deal, NormalizedPost.emojis, NormalizedPost.hashtags,
            NormalizedPost.cta_texts, NormalizedPost.primary_merchant_key,
        ).where(NormalizedPost.source_type == SourceType.COMPETITOR)
    ).all()
    src_ids = [r[0] for r in np_rows]
    cp_rows = {
        cid: (competitor_id, posted_at, tlen, media, views)
        for cid, competitor_id, posted_at, tlen, media, views in s.execute(
            select(
                CompetitorPost.id, CompetitorPost.competitor_id, CompetitorPost.posted_at,
                _len(CompetitorPost.text), CompetitorPost.has_media, CompetitorPost.views,
            )
        ).all()
    }
    clusters, total_links, known_links = _feature_maps(s, SourceType.COMPETITOR, src_ids)

    from src.db.models import Competitor
    usernames = dict(s.execute(select(Competitor.id, Competitor.username)).all())

    groups: dict[int, ChannelBehaviour] = {}
    for src_id, num_links, has_coupon, multi, emojis, hashtags, cta, mkey in np_rows:
        meta = cp_rows.get(src_id)
        if not meta:
            continue
        competitor_id, posted_at, tlen, media, views = meta
        g = groups.setdefault(
            competitor_id, ChannelBehaviour(label=usernames.get(competitor_id, str(competitor_id)))
        )
        g.features.append(PostFeature(
            posted_at=posted_at, text_len=tlen or 0, has_media=bool(media), views=views,
            num_links=num_links, has_coupon=has_coupon, is_multi_deal=multi,
            emoji_count=len(emojis or []), hashtag_count=len(hashtags or []),
            has_cta=bool(cta), merchant_key=mkey, cluster=clusters.get(src_id),
            known_link_count=known_links.get(src_id, 0),
            total_link_count=total_links.get(src_id, 0),
        ))
    return groups, usernames


def _len(col):
    from sqlalchemy import func

    return func.length(col)
