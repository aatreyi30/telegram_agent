"""Phase 4 storage — Merchant Intelligence outputs.

Honest-by-construction (README/13 "Failure Handling" + RULE 1): fields the data
cannot support are represented as explicit *availability flags* set to False and
left NULL, never estimated. Scores reference measurable metrics only and always
carry a confidence + sample size, so a profile built from 1 post is never
presented as if it were authoritative.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin

MERCHANT_INTEL_VERSION = 1


class MerchantProfile(Base, TimestampMixin):
    """Continuously-updated intelligence profile for one merchant."""

    __tablename__ = "merchant_profiles"
    __table_args__ = (
        UniqueConstraint("intel_version", "merchant_key", name="uq_profile_ver_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    intel_version: Mapped[int] = mapped_column(Integer, default=MERCHANT_INTEL_VERSION)
    merchant_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"))

    # activity
    post_count_owned: Mapped[int] = mapped_column(Integer, default=0)
    first_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    days_active: Mapped[int | None] = mapped_column(Integer)
    active_weeks: Mapped[int | None] = mapped_column(Integer)
    posting_consistency: Mapped[float | None] = mapped_column(Float)  # active_weeks / span_weeks

    # engagement (owned) — age-normalized to control for cumulative view inflation
    avg_views: Mapped[float | None] = mapped_column(Float)
    median_views: Mapped[float | None] = mapped_column(Float)
    avg_views_per_day: Mapped[float | None] = mapped_column(Float)
    avg_forwards: Mapped[float | None] = mapped_column(Float)
    avg_reactions: Mapped[float | None] = mapped_column(Float)
    engagement_sample_size: Mapped[int] = mapped_column(Integer, default=0)

    # pricing (from extracted prices)
    price_min: Mapped[float | None] = mapped_column(Float)
    price_max: Mapped[float | None] = mapped_column(Float)
    price_avg: Mapped[float | None] = mapped_column(Float)
    price_median: Mapped[float | None] = mapped_column(Float)
    price_sample_size: Mapped[int] = mapped_column(Integer, default=0)

    # explicit availability flags for data we do NOT have (never estimated)
    discount_available: Mapped[bool] = mapped_column(Boolean, default=False)
    category_available: Mapped[bool] = mapped_column(Boolean, default=False)
    conversion_available: Mapped[bool] = mapped_column(Boolean, default=False)

    # post-type (learned cluster) distribution — proxy for the missing category dim
    cluster_distribution: Mapped[dict | None] = mapped_column(JSON)

    # competitor presence
    competitor_count: Mapped[int] = mapped_column(Integer, default=0)
    competitor_post_count: Mapped[int] = mapped_column(Integer, default=0)

    # transparent, metric-referenced scores (NULL when not comparable) + confidence
    performance_score: Mapped[float | None] = mapped_column(Float)
    popularity_score: Mapped[float | None] = mapped_column(Float)
    consistency_score: Mapped[float | None] = mapped_column(Float)
    opportunity_score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[dict | None] = mapped_column(JSON)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    windows: Mapped[list["MerchantMetricWindow"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class MerchantMetricWindow(Base):
    """Time-windowed metrics for a merchant (7/30/90/365 days). History is
    preserved by never overwriting older window rows from prior runs."""

    __tablename__ = "merchant_metric_windows"
    __table_args__ = (Index("ix_mmw_key_window", "merchant_key", "window_days"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("merchant_profiles.id"), nullable=False)
    merchant_key: Mapped[str] = mapped_column(String(64), nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)  # 0 = all-time
    post_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_views: Mapped[float | None] = mapped_column(Float)
    avg_views_per_day: Mapped[float | None] = mapped_column(Float)
    avg_forwards: Mapped[float | None] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    profile: Mapped["MerchantProfile"] = relationship(back_populates="windows")


class MerchantOpportunity(Base):
    """An evidence-backed merchant opportunity (README/13 opportunity detection).

    Only created when the data actually supports it — every row carries its
    supporting evidence and a confidence. Never speculative."""

    __tablename__ = "merchant_opportunities"
    __table_args__ = (Index("ix_mopp_key", "merchant_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    intel_version: Mapped[int] = mapped_column(Integer, default=MERCHANT_INTEL_VERSION)
    merchant_key: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
