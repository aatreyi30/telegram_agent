"""Subscriber growth analytics from participant snapshots.

Tracks how the owned channel's participant count changes over time by reading
the lightweight ParticipantSnapshot rows written on every collection cycle.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections import OrderedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Channel
from src.db.models_growth_snapshot import ParticipantSnapshot


def compute_growth(s: Session, channel_id: int, days: int = 90) -> dict:
    """Compute subscriber growth metrics from participant snapshots."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = s.scalars(
        select(ParticipantSnapshot)
        .where(
            ParticipantSnapshot.channel_id == channel_id,
            ParticipantSnapshot.captured_at >= cutoff,
        )
        .order_by(ParticipantSnapshot.captured_at)
    ).all()

    if len(rows) < 2:
        return {"available": False, "reason": "Need at least 2 snapshots to show a trend. Snapshots are taken on each collection cycle.", "snapshots": len(rows)}

    first, last = rows[0], rows[-1]
    net_change = (last.count or 0) - (first.count or 0)
    span_seconds = (last.captured_at - first.captured_at).total_seconds()
    span_days = max(span_seconds / 86400, 1.0)
    growth_per_day = round(net_change / span_days, 1) if first.count is not None else None
    growth_rate_pct = round(((last.count or 0) - (first.count or 0)) / max(first.count or 1, 1) * 100, 2)

    # daily deltas
    daily_map: dict[str, dict] = OrderedDict()
    prev = None
    for r in rows:
        day_key = r.captured_at.astimezone(timezone.utc).strftime("%Y-%m-%d")
        delta = None
        if prev is not None and r.count is not None and prev.count is not None:
            delta = r.count - prev.count
        if day_key in daily_map:
            daily_map[day_key] = {"count": r.count, "delta": delta}
        else:
            daily_map[day_key] = {"count": r.count, "delta": delta}
        prev = r

    return {
        "available": True,
        "current": last.count,
        "first": first.count,
        "first_date": first.captured_at.isoformat(),
        "last_date": last.captured_at.isoformat(),
        "net_change": net_change,
        "span_days": round(span_days, 1),
        "growth_per_day": growth_per_day,
        "growth_rate_pct": growth_rate_pct,
        "snapshots": len(rows),
        "daily": [{"date": d, "count": v["count"], "delta": v["delta"]} for d, v in daily_map.items()],
    }


def get_growth(s: Session) -> dict:
    """Get growth for the primary owned channel."""
    ch = s.scalar(select(Channel).where(Channel.kind == "owned").order_by(Channel.participants_count.desc()))
    if not ch:
        return {"available": False, "reason": "No owned channel found."}
    return compute_growth(s, ch.id)
