"""Day-wise aggregate report row — the compact artifact the AI reasons over.

One row per (channel_id, report_date, source_type). Computed nightly by a
deterministic aggregator (services/analytics/daily_report.py) from per-post rows
+ metric snapshots. Applies to owned AND competitor channels (source_type), so
the AI compares on identical footing. Persisting this is the single most
important wiring fix: yesterday's actuals now reach today's plan.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, TimestampMixin

REPORT_VERSION = 1


class ReportSourceType:
    OWNED = "owned"
    COMPETITOR = "competitor"


class DailyChannelReport(Base, TimestampMixin):
    __tablename__ = "daily_channel_reports"
    __table_args__ = (
        UniqueConstraint("channel_id", "report_date", "source_type", name="uq_daily_report"),
        Index("ix_daily_report_date", "report_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    report_version: Mapped[int] = mapped_column(Integer, default=REPORT_VERSION)

    # volume
    posts_count: Mapped[int] = mapped_column(Integer, default=0)
    deals_posted: Mapped[int] = mapped_column(Integer, default=0)
    merchants_featured: Mapped[int] = mapped_column(Integer, default=0)

    # views
    views_total: Mapped[int] = mapped_column(Integer, default=0)
    views_avg: Mapped[float] = mapped_column(Float, default=0.0)
    views_median: Mapped[float] = mapped_column(Float, default=0.0)
    views_max: Mapped[int] = mapped_column(Integer, default=0)
    views_min: Mapped[int] = mapped_column(Integer, default=0)
    top_post_id: Mapped[int | None] = mapped_column(Integer)      # tg message id / post id
    bottom_post_id: Mapped[int | None] = mapped_column(Integer)

    # engagement
    reactions_total: Mapped[int] = mapped_column(Integer, default=0)
    forwards_total: Mapped[int] = mapped_column(Integer, default=0)
    engagement_rate: Mapped[float] = mapped_column(Float, default=0.0)

    # audience
    subs_start: Mapped[int | None] = mapped_column(Integer)
    subs_end: Mapped[int | None] = mapped_column(Integer)
    subs_net: Mapped[int | None] = mapped_column(Integer)

    # composition
    type_mix: Mapped[dict | None] = mapped_column(JSON)
    category_mix: Mapped[dict | None] = mapped_column(JSON)
    posting_hours: Mapped[dict | None] = mapped_column(JSON)
    best_category: Mapped[str | None] = mapped_column(String(64))
    worst_category: Mapped[str | None] = mapped_column(String(64))

    # provenance
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_completeness: Mapped[float] = mapped_column(Float, default=1.0)
