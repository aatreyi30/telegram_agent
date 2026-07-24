"""Participant count snapshots — time-series of Channel.participants_count.

Created on every collection cycle so we can show subscriber growth trends
without needing Telegram admin-level stats (which require can_view_stats).
"""

from __future__ import annotations

from datetime import date as date_, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
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


class DailySubscriberStat(Base):
    """Per-IST-day rollup of subscriber joins/leaves, built incrementally as each
    collection cycle observes a new participant count (see
    ``telegram_owned.py::_upsert_daily_subscriber_stat``).

    Unlike ``ParticipantSnapshot`` (a raw point-in-time reading), this table holds
    one row per (channel, day) that accumulates joined/left counts across the day's
    collection cycles, so the dashboard can show daily net growth without having to
    reconstruct it from potentially-gappy snapshots at read time.
    """

    __tablename__ = "daily_subscriber_stats"
    __table_args__ = (
        UniqueConstraint("channel_id", "stat_date", name="uq_dailysub_channel_date"),
        Index("ix_dailysub_channel_date", "channel_id", "stat_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    stat_date: Mapped[date_] = mapped_column(Date, nullable=False)  # IST calendar day

    subs_start: Mapped[int] = mapped_column(Integer)   # first observed count that day
    subs_end: Mapped[int] = mapped_column(Integer)      # most recent observed count that day
    subs_joined: Mapped[int] = mapped_column(Integer, default=0)
    subs_left: Mapped[int] = mapped_column(Integer, default=0)
    subs_net: Mapped[int] = mapped_column(Integer, default=0)
    # 1 for a normal day. >1 when this row's delta was seeded from a PRIOR row more
    # than a day old (a collection gap) — the whole gap's joined/left/net total
    # lands on this one calendar day, so consumers must not read it as "one day's
    # growth" without checking this field first. See _upsert_daily_subscriber_stat.
    spans_days: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DailyViewSource(Base):
    """Per-IST-day view counts broken out by traffic source ("search", a named
    channel, "other", ...), sourced from Telegram's admin-only
    ``views_by_source_graph`` (``stats.getBroadcastStats`` — requires
    ``Channel.can_view_stats``; see
    ``telegram_owned.py::_collect_broadcast_stats``). One row per
    (channel, day, source); Telegram's graph is the source of truth so a
    resync simply overwrites the value rather than accumulating a delta.
    """

    __tablename__ = "daily_view_sources"
    __table_args__ = (
        UniqueConstraint("channel_id", "stat_date", "source_label", name="uq_dailyviewsrc_channel_date_src"),
        Index("ix_dailyviewsrc_channel_date", "channel_id", "stat_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    stat_date: Mapped[date_] = mapped_column(Date, nullable=False)  # IST calendar day
    source_label: Mapped[str] = mapped_column(String(64), nullable=False)

    views: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DailyJoinSource(Base):
    """Per-IST-day new-follower counts broken out by source, sourced from
    Telegram's admin-only ``new_followers_by_source_graph``. Same conventions
    as ``DailyViewSource`` above."""

    __tablename__ = "daily_join_sources"
    __table_args__ = (
        UniqueConstraint("channel_id", "stat_date", "source_label", name="uq_dailyjoinsrc_channel_date_src"),
        Index("ix_dailyjoinsrc_channel_date", "channel_id", "stat_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    stat_date: Mapped[date_] = mapped_column(Date, nullable=False)  # IST calendar day
    source_label: Mapped[str] = mapped_column(String(64), nullable=False)

    joins: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
