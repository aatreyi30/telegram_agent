"""Phase 6 storage — Channel Learning Engine outputs.

Reusable, evidence-backed knowledge learned from the owned channel's history:
a style profile, per-post-type performance, and discrete learning records that
the Growth Engine (Phase 7) will consume. Everything is data-derived; unknowns
(subscriber attribution, CTR) are absent, never estimated. Records are versioned
so learning history is preserved (never overwritten destructively across
versions).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, TimestampMixin

LEARNING_VERSION = 1


class ChannelStyleProfile(Base, TimestampMixin):
    """One learned style/behaviour profile for the owned channel."""

    __tablename__ = "channel_style_profiles"
    __table_args__ = (UniqueConstraint("learning_version", name="uq_style_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), index=True)
    learning_version: Mapped[int] = mapped_column(Integer, default=LEARNING_VERSION)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    post_count: Mapped[int] = mapped_column(Integer, default=0)

    # style
    avg_caption_len: Mapped[float | None] = mapped_column(Float)
    median_caption_len: Mapped[float | None] = mapped_column(Float)
    avg_emojis: Mapped[float | None] = mapped_column(Float)
    top_emojis: Mapped[list | None] = mapped_column(JSON)      # [[emoji, count], ...]
    hashtag_rate: Mapped[float | None] = mapped_column(Float)
    cta_rate: Mapped[float | None] = mapped_column(Float)
    coupon_rate: Mapped[float | None] = mapped_column(Float)
    multi_deal_rate: Mapped[float | None] = mapped_column(Float)
    avg_links: Mapped[float | None] = mapped_column(Float)
    media_rate: Mapped[float | None] = mapped_column(Float)

    # behaviour / timing (IST)
    posts_per_day: Mapped[float | None] = mapped_column(Float)
    posts_per_week: Mapped[float | None] = mapped_column(Float)
    top_hours_ist: Mapped[list | None] = mapped_column(JSON)   # [[hour, count], ...]
    top_weekdays: Mapped[list | None] = mapped_column(JSON)
    posting_consistency: Mapped[float | None] = mapped_column(Float)

    confidence: Mapped[float] = mapped_column(Float, default=0.0)


class PostTypePerformance(Base):
    """Age-normalized performance of each learned post type (cluster)."""

    __tablename__ = "post_type_performance"
    __table_args__ = (
        UniqueConstraint("learning_version", "post_type", name="uq_ptperf"),
        Index("ix_ptperf_rank", "rank_by_views_per_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), index=True)
    learning_version: Mapped[int] = mapped_column(Integer, default=LEARNING_VERSION)
    post_type: Mapped[str] = mapped_column(String(255), nullable=False)  # cluster descriptor
    post_count: Mapped[int] = mapped_column(Integer, default=0)
    share: Mapped[float | None] = mapped_column(Float)
    avg_views: Mapped[float | None] = mapped_column(Float)
    avg_views_per_day: Mapped[float | None] = mapped_column(Float)
    avg_forwards: Mapped[float | None] = mapped_column(Float)
    avg_reactions: Mapped[float | None] = mapped_column(Float)
    rank_by_views_per_day: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LearningRecord(Base):
    """A discrete, evidence-backed thing the platform learned.

    Consumed by the Growth Engine. Every record states what was measured, the
    supporting numbers, the sample size, and a confidence — never a bare claim.
    """

    __tablename__ = "learning_records"
    __table_args__ = (Index("ix_learning_category", "category"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), index=True)
    learning_version: Mapped[int] = mapped_column(Integer, default=LEARNING_VERSION)
    category: Mapped[str] = mapped_column(String(64), nullable=False)  # timing/cta/emoji/...
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    metric_name: Mapped[str | None] = mapped_column(String(64))
    metric_value: Mapped[float | None] = mapped_column(Float)
    comparison_value: Mapped[float | None] = mapped_column(Float)  # e.g. channel baseline
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[dict | None] = mapped_column(JSON)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
