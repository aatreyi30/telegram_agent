"""Phase 7 storage — Growth Engine outputs.

The Growth Engine defines WHAT to do (strategy + recommendations), never the
final posts (that is Phase 9). Two modes (README/25): COLD START (bootstrap from
competitors) and OPTIMIZATION (personalized from own learning). Every
recommendation carries reasoning + evidence + confidence + priority (RULE:
no recommendation without evidence).
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin

GROWTH_VERSION = 1


class GrowthMode:
    COLD_START = "cold_start"
    OPTIMIZATION = "optimization"


class GrowthStrategy(Base, TimestampMixin):
    """The channel identity blueprint + strategy for one run."""

    __tablename__ = "growth_strategies"
    __table_args__ = (UniqueConstraint("growth_version", name="uq_growth_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), index=True)
    growth_version: Mapped[int] = mapped_column(Integer, default=GROWTH_VERSION)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    channel_type: Mapped[str | None] = mapped_column(String(64))  # derived from learned mix
    blueprint: Mapped[dict] = mapped_column(JSON)                 # frequency/timing/mix/cta/...
    data_basis: Mapped[dict | None] = mapped_column(JSON)         # what it was derived from
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    recommendations: Mapped[list["GrowthRecommendation"]] = relationship(
        back_populates="strategy", cascade="all, delete-orphan"
    )


class GrowthRecommendation(Base):
    __tablename__ = "growth_recommendations"
    __table_args__ = (Index("ix_growthrec_priority", "priority"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), index=True)
    growth_version: Mapped[int] = mapped_column(Integer, default=GROWTH_VERSION)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("growth_strategies.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    priority: Mapped[int] = mapped_column(Integer, default=99)  # 1 = highest
    expected_outcome: Mapped[str | None] = mapped_column(String(255))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    strategy: Mapped["GrowthStrategy"] = relationship(back_populates="recommendations")
