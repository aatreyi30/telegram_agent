"""Raw per-merchant metric aggregation from stored facts.

Consumes owned Posts (engagement), Phase-2 normalized entities (merchant,
prices), and Phase-3 clusters (post-type distribution). Age-normalizes views to
control for the fact that Telegram view counts are cumulative totals — older
posts accrue more views purely from age (Data Validation Matrix Feature 15).

Returns plain data structures; assigns NO meaning and computes NO scores.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import CompetitorPost, Post
from src.db.models_classification import PostClassification, PostTypeCluster
from src.db.models_normalization import (
    ExtractedPrice,
    NormalizedPost,
    SourceType,
)

WINDOWS = [7, 30, 90, 365, 0]  # 0 = all-time


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; we always store UTC, so treat naive as UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@dataclass
class OwnedPostFact:
    normalized_post_id: int
    posted_at: datetime | None
    views: int | None
    forwards: int | None
    reactions: int | None


@dataclass
class MerchantMetrics:
    merchant_key: str
    posts: list[OwnedPostFact] = field(default_factory=list)
    prices: list[float] = field(default_factory=list)
    cluster_counts: dict[str, int] = field(default_factory=dict)
    competitor_ids: set[int] = field(default_factory=set)
    competitor_post_count: int = 0

    # ---- derived helpers (raw stats only) ----
    def _views(self) -> list[int]:
        return [p.views for p in self.posts if p.views is not None]

    def _views_per_day(self, now: datetime) -> list[float]:
        out = []
        for p in self.posts:
            if p.views is None or p.posted_at is None:
                continue
            age_days = max((now - p.posted_at).total_seconds() / 86400.0, 1.0)
            out.append(p.views / age_days)
        return out

    def summary(self, now: datetime) -> dict:
        views = self._views()
        vpd = self._views_per_day(now)
        forwards = [p.forwards for p in self.posts if p.forwards is not None]
        reactions = [p.reactions for p in self.posts if p.reactions is not None]
        dated = [p.posted_at for p in self.posts if p.posted_at]
        span_weeks = None
        active_weeks = None
        if dated:
            first, last = min(dated), max(dated)
            span_days = max((last - first).days, 0) + 1
            span_weeks = max(span_days / 7.0, 1.0)
            active_weeks = len({(d.isocalendar().year, d.isocalendar().week) for d in dated})
        return {
            "post_count": len(self.posts),
            "first_posted_at": min(dated) if dated else None,
            "last_posted_at": max(dated) if dated else None,
            "days_active": len({d.date() for d in dated}) if dated else None,
            "active_weeks": active_weeks,
            "span_weeks": span_weeks,
            "avg_views": statistics.fmean(views) if views else None,
            "median_views": statistics.median(views) if views else None,
            "avg_views_per_day": statistics.fmean(vpd) if vpd else None,
            "avg_forwards": statistics.fmean(forwards) if forwards else None,
            "avg_reactions": statistics.fmean(reactions) if reactions else None,
            "engagement_sample_size": len(views),
            "price_min": min(self.prices) if self.prices else None,
            "price_max": max(self.prices) if self.prices else None,
            "price_avg": statistics.fmean(self.prices) if self.prices else None,
            "price_median": statistics.median(self.prices) if self.prices else None,
            "price_sample_size": len(self.prices),
            "cluster_distribution": dict(self.cluster_counts) or None,
            "competitor_count": len(self.competitor_ids),
            "competitor_post_count": self.competitor_post_count,
        }

    def window_summary(self, now: datetime, window_days: int) -> dict:
        if window_days == 0:
            posts = self.posts
        else:
            cutoff = now - timedelta(days=window_days)
            posts = [p for p in self.posts if p.posted_at and p.posted_at >= cutoff]
        views = [p.views for p in posts if p.views is not None]
        vpd = []
        forwards = [p.forwards for p in posts if p.forwards is not None]
        for p in posts:
            if p.views is not None and p.posted_at is not None:
                age = max((now - p.posted_at).total_seconds() / 86400.0, 1.0)
                vpd.append(p.views / age)
        return {
            "window_days": window_days,
            "post_count": len(posts),
            "avg_views": statistics.fmean(views) if views else None,
            "avg_views_per_day": statistics.fmean(vpd) if vpd else None,
            "avg_forwards": statistics.fmean(forwards) if forwards else None,
        }


def compute_merchant_metrics(s: Session) -> dict[str, MerchantMetrics]:
    """Aggregate all stored facts into per-merchant metric bundles."""
    metrics: dict[str, MerchantMetrics] = {}

    def bucket(key: str) -> MerchantMetrics:
        return metrics.setdefault(key, MerchantMetrics(merchant_key=key))

    # 1) owned posts with a known merchant + their engagement
    owned = s.execute(
        select(
            NormalizedPost.id,
            NormalizedPost.primary_merchant_key,
            Post.posted_at,
            Post.views,
            Post.forwards,
            Post.reactions_total,
        )
        .join(Post, Post.id == NormalizedPost.source_id)
        .where(
            NormalizedPost.source_type == SourceType.OWNED,
            NormalizedPost.primary_merchant_key.isnot(None),
        )
    ).all()
    npid_to_merchant: dict[int, str] = {}
    for npid, mkey, posted_at, views, forwards, reactions in owned:
        bucket(mkey).posts.append(
            OwnedPostFact(npid, _aware(posted_at), views, forwards, reactions)
        )
        npid_to_merchant[npid] = mkey

    # 2) prices for those normalized posts
    if npid_to_merchant:
        price_rows = s.execute(
            select(ExtractedPrice.normalized_post_id, ExtractedPrice.amount).where(
                ExtractedPrice.normalized_post_id.in_(list(npid_to_merchant.keys()))
            )
        ).all()
        for npid, amt in price_rows:
            mkey = npid_to_merchant.get(npid)
            if mkey:
                bucket(mkey).prices.append(amt)

        # 3) cluster (post-type) distribution
        cluster_rows = s.execute(
            select(PostClassification.normalized_post_id, PostTypeCluster.descriptor)
            .join(PostTypeCluster, PostTypeCluster.id == PostClassification.cluster_id)
            .where(PostClassification.normalized_post_id.in_(list(npid_to_merchant.keys())))
        ).all()
        for npid, descriptor in cluster_rows:
            mkey = npid_to_merchant.get(npid)
            if mkey:
                d = bucket(mkey).cluster_counts
                label = descriptor or "unlabeled"
                d[label] = d.get(label, 0) + 1

    # 4) competitor usage (where competitor merchant is known)
    comp = s.execute(
        select(NormalizedPost.source_id, NormalizedPost.primary_merchant_key)
        .where(
            NormalizedPost.source_type == SourceType.COMPETITOR,
            NormalizedPost.primary_merchant_key.isnot(None),
        )
    ).all()
    comp_ids = [sid for sid, _ in comp]
    comp_to_competitor: dict[int, int] = {}
    if comp_ids:
        for cp_id, competitor_id in s.execute(
            select(CompetitorPost.id, CompetitorPost.competitor_id).where(
                CompetitorPost.id.in_(comp_ids)
            )
        ).all():
            comp_to_competitor[cp_id] = competitor_id
    for source_id, mkey in comp:
        b = bucket(mkey)
        b.competitor_post_count += 1
        cid = comp_to_competitor.get(source_id)
        if cid is not None:
            b.competitor_ids.add(cid)

    return metrics
