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
from src.db.models_normalization import (
    ExtractedLink,
    NormalizedPost,
    SourceType,
)
from src.logger import get_logger

logger = get_logger(__name__)

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
    link_merchants: list[str]
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
        logger.info("[competitor_metrics] summary: label=%s total_features=%d", self.label, n)
        
        dated = [_aware(p.posted_at) for p in f if p.posted_at]
        span_days = None
        posts_per_day = None
        if dated:
            span_days = max((max(dated) - min(dated)).days, 0) + 1
            posts_per_day = round(n / span_days, 3)
        logger.info("[competitor_metrics] summary: label=%s dated_posts=%d span_days=%s posts_per_day=%s", self.label, len(dated), span_days, posts_per_day)
        
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
        merchant_mix = Counter()
        for p in f:
            for mk in p.link_merchants:
                if mk:
                    merchant_mix[mk] += 1
        total_links = sum(p.total_link_count for p in f)
        known_links = sum(p.known_link_count for p in f)
        coverage = round(known_links / total_links, 3) if total_links else 0.0
        logger.info("[competitor_metrics] metrics computed: label=%s merchant_mix=%s merchant_coverage=%s total_links=%d known_links=%d", self.label, dict(merchant_mix), coverage, total_links, known_links)

        def rate(pred) -> float | None:
            return round(sum(1 for p in f if pred(p)) / n, 3) if n else None

        def mean(vals) -> float | None:
            return round(statistics.fmean(vals), 3) if vals else None

        result = {
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
        logger.info("[competitor_metrics] summary complete: label=%s post_count=%s posts_per_day=%s merchant_coverage=%s", self.label, result["post_count"], result["posts_per_day"], result["merchant_coverage"])
        return result


def _feature_maps(s: Session, source_type: str, source_ids: list[int]):
    """cluster + resolved-link counts + link-level merchant keys for a set of normalized_post ids."""
    if not source_ids:
        logger.info("[competitor_metrics] no source_ids provided for feature_maps")
        return {}, {}, {}, {}
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
    logger.info("[competitor_metrics] feature_maps: source_type=%s source_ids_count=%d normalized_posts_count=%d", source_type, len(source_ids), len(npids))

    clusters: dict[int, str] = {}

    # link counts (total + resolved-merchant) + link merchants per source post
    total_links: dict[int, int] = {}
    known_links: dict[int, int] = {}
    link_merchants: dict[int, list[str]] = {}
    if npids:
        for npid, mkey in s.execute(
            select(ExtractedLink.normalized_post_id, ExtractedLink.merchant_key)
            .where(ExtractedLink.normalized_post_id.in_(npids))
        ).all():
            src = npid_to_src[npid]
            total_links[src] = total_links.get(src, 0) + 1
            if mkey:
                known_links[src] = known_links.get(src, 0) + 1
                link_merchants.setdefault(src, []).append(mkey)
        logger.info("[competitor_metrics] link counts: total_links=%d known_links=%d", sum(total_links.values()), sum(known_links.values()))
    return clusters, total_links, known_links, link_merchants


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
    logger.info("[competitor_metrics] compute_owned_behaviour: normalized_posts=%d source_ids=%d", len(np_rows), len(src_ids))
    
    # Only fetch Post rows that match the normalized posts (fix data mismatch)
    post_rows = {}
    if src_ids:
        post_rows = {
            pid: (posted_at, tlen, media, views)
            for pid, posted_at, tlen, media, views in s.execute(
                select(Post.id, Post.posted_at, _len(Post.text), Post.has_media, Post.views)
                .where(Post.id.in_(src_ids))
            ).all()
        }
    logger.info("[competitor_metrics] compute_owned_behaviour: matched_posts=%d", len(post_rows))
    
    clusters, total_links, known_links, link_merchants = _feature_maps(s, SourceType.OWNED, src_ids)
    skipped_count = 0
    for src_id, num_links, has_coupon, multi, emojis, hashtags, cta, mkey in np_rows:
        meta = post_rows.get(src_id)
        if not meta:
            skipped_count += 1
            continue
        posted_at, tlen, media, views = meta
        ch.features.append(PostFeature(
            posted_at=posted_at, text_len=tlen or 0, has_media=bool(media), views=views,
            num_links=num_links, has_coupon=has_coupon, is_multi_deal=multi,
            emoji_count=len(emojis or []), hashtag_count=len(hashtags or []),
            has_cta=bool(cta), merchant_key=mkey, link_merchants=link_merchants.get(src_id, []),
            cluster="loot_deal" if multi else "single_deal",
            known_link_count=known_links.get(src_id, 0),
            total_link_count=total_links.get(src_id, 0),
        ))
    logger.info("[competitor_metrics] compute_owned_behaviour: skipped_posts_without_match=%d", skipped_count)
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
    logger.info("[competitor_metrics] compute_competitor_behaviours: normalized_posts=%d source_ids=%d", len(np_rows), len(src_ids))
    
    # Only fetch CompetitorPost rows that match the normalized posts (fix data mismatch)
    cp_rows = {}
    if src_ids:
        cp_rows = {
            cid: (competitor_id, posted_at, tlen, media, views)
            for cid, competitor_id, posted_at, tlen, media, views in s.execute(
                select(
                    CompetitorPost.id, CompetitorPost.competitor_id, CompetitorPost.posted_at,
                    _len(CompetitorPost.text), CompetitorPost.has_media, CompetitorPost.views,
                ).where(CompetitorPost.id.in_(src_ids))
            ).all()
        }
    logger.info("[competitor_metrics] compute_competitor_behaviours: matched_competitor_posts=%d", len(cp_rows))
    
    clusters, total_links, known_links, link_merchants = _feature_maps(s, SourceType.COMPETITOR, src_ids)

    from src.db.models import Competitor
    usernames = dict(s.execute(select(Competitor.id, Competitor.username)).all())

    groups: dict[int, ChannelBehaviour] = {}
    skipped_count = 0
    for src_id, num_links, has_coupon, multi, emojis, hashtags, cta, mkey in np_rows:
        meta = cp_rows.get(src_id)
        if not meta:
            skipped_count += 1
            continue
        competitor_id, posted_at, tlen, media, views = meta
        g = groups.setdefault(
            competitor_id, ChannelBehaviour(label=usernames.get(competitor_id, str(competitor_id)))
        )
        g.features.append(PostFeature(
            posted_at=posted_at, text_len=tlen or 0, has_media=bool(media), views=views,
            num_links=num_links, has_coupon=has_coupon, is_multi_deal=multi,
            emoji_count=len(emojis or []), hashtag_count=len(hashtags or []),
            has_cta=bool(cta), merchant_key=mkey, link_merchants=link_merchants.get(src_id, []),
            cluster="loot_deal" if multi else "single_deal",
            known_link_count=known_links.get(src_id, 0),
            total_link_count=total_links.get(src_id, 0),
        ))
    logger.info("[competitor_metrics] compute_competitor_behaviours: skipped_posts_without_match=%d", skipped_count)
    return groups, usernames


def _len(col):
    from sqlalchemy import func

    return func.length(col)
