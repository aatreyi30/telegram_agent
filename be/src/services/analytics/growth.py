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
from src.db.models_growth_snapshot import DailySubscriberStat, ParticipantSnapshot
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


def compute_growth(s: Session, channel_id: int, start: DateLike = None, end: DateLike = None) -> dict:
    """Compute subscriber growth metrics from daily subscriber stats for one channel."""
    start_d, end_d = _to_ist_date(start), _to_ist_date(end)

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
    }


def get_growth(s: Session, start: DateLike = None, end: DateLike = None) -> dict:
    """Get growth for the primary owned channel, optionally scoped to [start, end]
    (inclusive IST calendar dates; a bare date or a datetime is accepted for each)."""
    ch = s.scalar(select(Channel).where(Channel.kind == "owned").order_by(Channel.participants_count.desc()))
    if not ch:
        return {"available": False, "reason": "No owned channel found."}
    return compute_growth(s, ch.id, start, end)
