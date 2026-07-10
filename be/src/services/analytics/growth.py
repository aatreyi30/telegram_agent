"""Subscriber growth analytics from daily subscriber stats.

Tracks how the owned channel's subscriber count changes over time by reading the
``DailySubscriberStat`` rows that are incrementally rolled up (joined/left/net per
IST calendar day) on every collection cycle — see
``services/collection/telegram_owned.py::_upsert_daily_subscriber_stat``.

Per explicit product-owner instruction, this module does NOT compute a growth
rate / growth-per-day projection — only the observed joined/left/net counts.
"""

from __future__ import annotations

from datetime import date as date_, datetime
from typing import Union

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Channel
from src.db.models_growth_snapshot import (
    DailyJoinSource,
    DailySubscriberStat,
    DailyViewSource,
    ParticipantSnapshot,
)
from src.services.analytics.periods import IST

DateLike = Union[date_, datetime, None]


def _to_ist_date(v: DateLike) -> date_ | None:
    """Normalize an optional date/datetime bound to a plain IST calendar date."""
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v if v.tzinfo else v.replace(tzinfo=IST)
        return dt.astimezone(IST).date()
    return v


def _source_breakdown(s: Session, model, channel_id: int, value_field: str,
                       start_d: date_ | None, end_d: date_ | None) -> dict:
    """Read a per-source daily table (DailyViewSource / DailyJoinSource) for a
    channel/date-range into ``{totals: {source: total}, daily: {date: {source: value}}}``."""
    q = select(model).where(model.channel_id == channel_id)
    if start_d is not None:
        q = q.where(model.stat_date >= start_d)
    if end_d is not None:
        q = q.where(model.stat_date <= end_d)
    rows = s.scalars(q.order_by(model.stat_date)).all()

    totals: dict[str, int] = {}
    daily: dict[str, dict[str, int]] = {}
    for r in rows:
        value = getattr(r, value_field) or 0
        totals[r.source_label] = totals.get(r.source_label, 0) + value
        daily.setdefault(r.stat_date.isoformat(), {})[r.source_label] = value
    return {"totals": totals, "daily": daily}


def compute_growth(
    s: Session,
    channel_id: int,
    start: DateLike = None,
    end: DateLike = None,
    can_view_stats: bool = False,
) -> dict:
    """Compute subscriber growth metrics from daily subscriber stats for one channel.

    ``view_sources``/``follower_sources`` (Telegram's admin-only "views by
    source" / "joins by source" breakdowns — see
    ``telegram_owned.py::_collect_broadcast_stats``) are included only when
    ``can_view_stats`` is true; otherwise both are ``None`` so the frontend can
    hide the section rather than show an empty/broken one.
    """
    start_d, end_d = _to_ist_date(start), _to_ist_date(end)
    view_sources = (
        _source_breakdown(s, DailyViewSource, channel_id, "views", start_d, end_d)
        if can_view_stats else None
    )
    follower_sources = (
        _source_breakdown(s, DailyJoinSource, channel_id, "joins", start_d, end_d)
        if can_view_stats else None
    )

    q = select(DailySubscriberStat).where(DailySubscriberStat.channel_id == channel_id)
    if start_d is not None:
        q = q.where(DailySubscriberStat.stat_date >= start_d)
    if end_d is not None:
        q = q.where(DailySubscriberStat.stat_date <= end_d)
    rows = s.scalars(q.order_by(DailySubscriberStat.stat_date)).all()

    # "current" must reflect the TRUE latest count regardless of the start/end filter —
    # read it straight off the latest ParticipantSnapshot, unaffected by date filtering.
    latest_snap = s.scalar(
        select(ParticipantSnapshot)
        .where(ParticipantSnapshot.channel_id == channel_id)
        .order_by(ParticipantSnapshot.captured_at.desc())
    )
    current = latest_snap.count if latest_snap else None

    if not rows:
        return {
            "available": False,
            "reason": "No daily subscriber stats yet. These accumulate as each "
                      "collection cycle observes the participant count.",
            "current": current,
            "days": 0,
            "view_sources": view_sources,
            "follower_sources": follower_sources,
        }

    joined = sum(r.subs_joined or 0 for r in rows)
    left = sum(r.subs_left or 0 for r in rows)
    net = sum(r.subs_net or 0 for r in rows)
    daily = [
        {
            "date": r.stat_date.isoformat(),
            "subs_end": r.subs_end,
            "joined": r.subs_joined or 0,
            "left": r.subs_left or 0,
            "net": r.subs_net or 0,
        }
        for r in rows
    ]

    return {
        "available": True,
        "current": current,
        "joined": joined,
        "left": left,
        "net": net,
        "days": len(rows),
        "first_date": rows[0].stat_date.isoformat(),
        "last_date": rows[-1].stat_date.isoformat(),
        "daily": daily,
        "view_sources": view_sources,
        "follower_sources": follower_sources,
    }


def get_growth(s: Session, start: DateLike = None, end: DateLike = None) -> dict:
    """Get growth for the primary owned channel, optionally scoped to [start, end]
    (inclusive IST calendar dates; a bare date or a datetime is accepted for each)."""
    ch = s.scalar(select(Channel).where(Channel.kind == "owned").order_by(Channel.participants_count.desc()))
    if not ch:
        return {"available": False, "reason": "No owned channel found."}
    return compute_growth(s, ch.id, start, end, can_view_stats=bool(ch.can_view_stats))
