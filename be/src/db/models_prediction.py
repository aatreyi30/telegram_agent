"""Phase 2.1 storage -- the Predict -> Outcome -> Retro loop's tables.

Two complementary paths (see upgrade.md Phase 2 design note), both permanent:
  * ``PostPrediction`` -- best-effort per post. Written when a draft is queued
    (``daily_planner.build_and_schedule_day``) and re-written/linked at
    publish time (``publishing.Publisher.publish``). ``post_id`` starts NULL
    (the post doesn't exist yet) and is backfilled once the real send lands.
  * ``PostOutcome`` -- computed for EVERY owned post (``outcomes.py``),
    whether or not a prediction exists. ``err_views_24h``/engagement are only
    ever null when the underlying snapshot data itself is missing.
  * ``WeeklyRetro`` -- the table for the weekly retro (engine built in a later
    pass); created now because it belongs with the rest of this loop's schema.

Dropped ``joins_attributed``/``leaves_attributed`` from the original spec --
those need Phase 1 (per-user attribution), which is out of scope this pass.
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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class PostPrediction(Base):
    __tablename__ = "post_predictions"
    __table_args__ = (
        Index("ix_post_predictions_generated_post", "generated_post_id"),
        Index("ix_post_predictions_post", "post_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    generated_post_id: Mapped[int | None] = mapped_column(ForeignKey("generated_posts.id"))
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"))  # backfilled at publish/link
    predicted_views_1h: Mapped[int | None] = mapped_column(Integer)
    predicted_views_6h: Mapped[int | None] = mapped_column(Integer)
    predicted_views_24h: Mapped[int | None] = mapped_column(Integer)
    predicted_forwards_24h: Mapped[int | None] = mapped_column(Integer)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)  # 'baseline_v1'
    features: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PostOutcome(Base):
    __tablename__ = "post_outcomes"

    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), primary_key=True)
    views_1h: Mapped[int | None] = mapped_column(Integer)
    views_6h: Mapped[int | None] = mapped_column(Integer)
    views_24h: Mapped[int | None] = mapped_column(Integer)
    forwards_24h: Mapped[int | None] = mapped_column(Integer)
    reactions_24h: Mapped[int | None] = mapped_column(Integer)
    forward_rate: Mapped[float | None] = mapped_column(Float)
    reaction_rate: Mapped[float | None] = mapped_column(Float)
    engagement_score: Mapped[float | None] = mapped_column(Float)
    err_views_24h: Mapped[float | None] = mapped_column(Float)  # (actual - predicted) / predicted
    phase_1h_done: Mapped[bool] = mapped_column(Boolean, default=False)
    phase_6h_done: Mapped[bool] = mapped_column(Boolean, default=False)
    phase_24h_done: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WeeklyRetro(Base):
    __tablename__ = "weekly_retros"
    __table_args__ = (UniqueConstraint("week_start", name="uq_weekly_retro_week"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)  # IST Monday
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    narrative: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
