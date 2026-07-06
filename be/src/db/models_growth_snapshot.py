"""Participant count snapshots — time-series of Channel.participants_count.

Created on every collection cycle so we can show subscriber growth trends
without needing Telegram admin-level stats (which require can_view_stats).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class ParticipantSnapshot(Base):
    """One observed participant count for a channel at a point in time."""

    __tablename__ = "participant_snapshots"
    __table_args__ = (Index("ix_partsnap_channel_time", "channel_id", "captured_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    count: Mapped[int | None] = mapped_column(Integer)
