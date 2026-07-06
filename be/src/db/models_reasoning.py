"""Phase 8 storage — Reasoning Engine outputs.

A ReasonedInsight explains WHY a metric shifted between two comparable periods.
Every insight carries the observed change, the evidence (numbers), a data-backed
reasoning (attribution to correlated measured changes — never a guess), and a
confidence. History is preserved across versions.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, TimestampMixin

REASONING_VERSION = 1


class ReasonedInsight(Base, TimestampMixin):
    __tablename__ = "reasoned_insights"
    __table_args__ = (Index("ix_insight_metric", "metric"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reasoning_version: Mapped[int] = mapped_column(Integer, default=REASONING_VERSION)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)     # engagement/volume/mix/...
    direction: Mapped[str] = mapped_column(String(8), nullable=False)   # up / down / flat
    change_value: Mapped[float | None] = mapped_column(Float)           # % or pp change
    change_unit: Mapped[str] = mapped_column(String(8), default="pct")  # pct | pp
    period_label: Mapped[str] = mapped_column(String(64), nullable=False)

    observation: Mapped[str] = mapped_column(Text, nullable=False)      # WHAT changed
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)        # WHY (data-backed)
    evidence: Mapped[dict] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
