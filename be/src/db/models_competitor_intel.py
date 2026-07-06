"""Phase 5 storage — Competitor Intelligence outputs.

Behaviour-first (README/15): profiles describe *how a competitor executes*
(posting cadence, content style, deal mix, timing), not just isolated numbers.
Every threat/opportunity carries evidence + confidence; unavailable dimensions
(forwards/reactions on t.me/s, business category, shortlink merchants) are
marked, never fabricated.
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
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, TimestampMixin

COMPETITOR_INTEL_VERSION = 1


class CompetitorProfile(Base, TimestampMixin):
    __tablename__ = "competitor_profiles"
    __table_args__ = (
        UniqueConstraint("intel_version", "competitor_id", name="uq_comp_profile"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    intel_version: Mapped[int] = mapped_column(Integer, default=COMPETITOR_INTEL_VERSION)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), nullable=False)
    username: Mapped[str] = mapped_column(String(128), nullable=False)

    # posting behaviour
    post_count: Mapped[int] = mapped_column(Integer, default=0)
    span_days: Mapped[int | None] = mapped_column(Integer)
    posts_per_day: Mapped[float | None] = mapped_column(Float)
    first_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # content style (rates 0..1 unless noted)
    avg_text_len: Mapped[float | None] = mapped_column(Float)
    emoji_rate: Mapped[float | None] = mapped_column(Float)      # avg emojis/post
    hashtag_rate: Mapped[float | None] = mapped_column(Float)    # avg hashtags/post
    cta_rate: Mapped[float | None] = mapped_column(Float)        # frac with CTA
    coupon_rate: Mapped[float | None] = mapped_column(Float)
    multi_deal_rate: Mapped[float | None] = mapped_column(Float)
    avg_links: Mapped[float | None] = mapped_column(Float)
    media_rate: Mapped[float | None] = mapped_column(Float)

    # engagement (t.me/s views only — rounded, cumulative; forwards/reactions N/A)
    avg_views: Mapped[float | None] = mapped_column(Float)
    views_sample_size: Mapped[int] = mapped_column(Integer, default=0)

    # timing (IST, since audience is Indian)
    top_posting_hour_ist: Mapped[int | None] = mapped_column(Integer)
    weekday_distribution: Mapped[dict | None] = mapped_column(JSON)
    hour_distribution_ist: Mapped[dict | None] = mapped_column(JSON)

    # mix
    deal_mix: Mapped[dict | None] = mapped_column(JSON)          # learned cluster mix
    merchant_mix: Mapped[dict | None] = mapped_column(JSON)      # known merchants only
    merchant_coverage: Mapped[float | None] = mapped_column(Float)  # frac links resolved
    category_available: Mapped[bool] = mapped_column(Boolean, default=False)

    # relation to us
    similarity_to_owned: Mapped[float | None] = mapped_column(Float)  # 0..1 cosine

    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CompetitorBenchmark(Base):
    """One dimension of our-channel-vs-competitor comparison (behaviour, not a
    single isolated metric — many rows together form the benchmark)."""

    __tablename__ = "competitor_benchmarks"
    __table_args__ = (Index("ix_bench_comp", "competitor_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    intel_version: Mapped[int] = mapped_column(Integer, default=COMPETITOR_INTEL_VERSION)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), nullable=False)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    dimension: Mapped[str] = mapped_column(String(64), nullable=False)
    owned_value: Mapped[float | None] = mapped_column(Float)
    competitor_value: Mapped[float | None] = mapped_column(Float)
    delta: Mapped[float | None] = mapped_column(Float)   # competitor - owned
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CompetitorSignal(Base):
    """An evidence-backed threat or opportunity (ranked by confidence)."""

    __tablename__ = "competitor_signals"
    __table_args__ = (Index("ix_signal_comp", "competitor_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    intel_version: Mapped[int] = mapped_column(Integer, default=COMPETITOR_INTEL_VERSION)
    competitor_id: Mapped[int | None] = mapped_column(ForeignKey("competitors.id"))
    username: Mapped[str | None] = mapped_column(String(128))
    signal_type: Mapped[str] = mapped_column(String(16), nullable=False)  # threat|opportunity
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
