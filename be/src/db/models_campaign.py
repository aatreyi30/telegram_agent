"""Phase 10 storage — Campaign & Planning Engine.

CampaignPlan converts approved intelligence into a structured execution plan
(daily / weekly / event) — merchant/deal-type/window allocation with expected
outcome + confidence + evidence. It does NOT contain captions or publish.

SaleEvent is the India deal calendar. Dates are marked exact (fixed national
dates) or approximate (merchant sales whose dates shift and are announced near
the event) — approximate dates are month-level and flagged, never fabricated as
precise (RULE 1).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
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

CAMPAIGN_VERSION = 1


class DateConfidence:
    EXACT = "exact"            # fixed calendar date (e.g. Independence Day)
    APPROXIMATE = "approximate"  # month-level; confirm near the event


class PlanType:
    DAILY = "daily"
    WEEKLY = "weekly"
    EVENT = "event"


class SaleEvent(Base, TimestampMixin):
    __tablename__ = "sale_events"
    __table_args__ = (UniqueConstraint("key", name="uq_sale_event_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32))  # festival | merchant_sale | shopping
    merchant_key: Mapped[str | None] = mapped_column(String(64))  # None = multi-merchant
    next_date: Mapped[date | None] = mapped_column(Date)
    window_days: Mapped[int] = mapped_column(Integer, default=3)
    date_confidence: Mapped[str] = mapped_column(String(16), default=DateConfidence.APPROXIMATE)
    recurrence: Mapped[str] = mapped_column(String(16), default="annual")
    notes: Mapped[str | None] = mapped_column(Text)


class CampaignPlan(Base, TimestampMixin):
    __tablename__ = "campaign_plans"
    __table_args__ = (Index("ix_plan_type_date", "plan_type", "target_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), index=True)
    campaign_version: Mapped[int] = mapped_column(Integer, default=CAMPAIGN_VERSION)
    plan_type: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)

    blueprint: Mapped[dict] = mapped_column(JSON)          # posts, schedule, allocations
    expected_outcome: Mapped[dict | None] = mapped_column(JSON)
    risks: Mapped[list | None] = mapped_column(JSON)
    evidence: Mapped[dict | None] = mapped_column(JSON)    # which decisions/learnings back it
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft/approved
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # --- AI analyst/planner provenance (rescue plan §2.5) ---
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_digest: Mapped[str | None] = mapped_column(Text)
    cited_numbers: Mapped[list | None] = mapped_column(JSON)
    factcheck_status: Mapped[str | None] = mapped_column(String(16))  # passed|failed|skipped
    report_ids: Mapped[list | None] = mapped_column(JSON)             # DailyChannelReport ids fed to the model
    # --- closed-loop feedback (§3.5) ---
    adherence: Mapped[dict | None] = mapped_column(JSON)              # planned vs published (deterministic)
    reconciliation: Mapped[dict | None] = mapped_column(JSON)         # expected-vs-actual + AI summary
