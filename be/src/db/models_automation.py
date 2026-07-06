"""Phase 11 storage — Automation Engine (scheduled posting queue).

A ScheduledPost is a queued send: a generated draft, a target channel, and a
fire time. The scheduler processes due items with retry/backoff and multi-channel
support. Idempotency: one (generated_post, channel) pair can only be queued once,
and a published item is never re-sent.

The actual send remains gated (admin rights + affiliate integration) — the queue
machinery is complete; blocked sends are recorded honestly, not faked.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, TimestampMixin

# ScheduledPost has a ForeignKey to generated_posts; importing the model here
# guarantees that table is registered on Base.metadata whenever this module is
# used in isolation (e.g. a CLI command that only imports ScheduledPost).
from src.db import models_generation  # noqa: F401,E402  (FK target registration)


class ScheduleStatus:
    QUEUED = "queued"        # waiting for scheduled_at
    RETRY = "retry"          # transient failure; will retry at next_attempt_at
    SENDING = "sending"      # in-flight
    PUBLISHED = "published"  # delivered
    FAILED = "failed"        # retries exhausted (transient errors)
    BLOCKED = "blocked"      # permanent (no post rights / integration missing)
    CANCELLED = "cancelled"


class ScheduledPost(Base, TimestampMixin):
    __tablename__ = "scheduled_posts"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_scheduled_idempotency"),
        Index("ix_scheduled_due", "status", "scheduled_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    generated_post_id: Mapped[int | None] = mapped_column(ForeignKey("generated_posts.id"))
    channel_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[str] = mapped_column(String(16), default=ScheduleStatus.QUEUED)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
