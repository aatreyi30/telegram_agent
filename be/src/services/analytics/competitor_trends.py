"""Cross-competitor daily trend charts (posts/day, views/day for every competitor
at once, sharing one calendar window). Every daily bucket goes through periods.py's
IST helpers; see test_ist_day_boundary.py for why a naive UTC-day bucketing is a
real, previously shipped bug.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import Competitor, CompetitorPost
from src.services.analytics.periods import ist_day_bounds_utc, to_ist


def _day_range(first_day: date, days: int):
    for i in range(days):
        yield first_day + timedelta(days=i)


def _latest_date_all(s: Session) -> date | None:
    mx = s.scalar(select(func.max(CompetitorPost.posted_at)))
    return to_ist(mx).date() if mx else None


def dashboard_trends(s: Session, days: int = 30) -> dict:
    """Posts/day and views/day for EVERY competitor at once, sharing one calendar
    window (anchored to the most recent post across all competitors, not per-competitor
    like the old per-competitor `_window()` — a stale competitor's "last N days" must not
    silently be an old window while an active one's is current, or the comparison chart
    would mislead)."""
    comps = s.execute(select(Competitor.id, Competitor.username)).all()
    if not comps:
        return {"dates": [], "posting_trend": [], "views_trend": [], "competitors": []}

    end_day = _latest_date_all(s)
    if end_day is None:
        return {"dates": [], "posting_trend": [], "views_trend": [], "competitors": []}
    first_day = end_day - timedelta(days=days - 1)
    start_utc, _ = ist_day_bounds_utc(first_day)
    _, end_utc = ist_day_bounds_utc(end_day)

    rows = s.execute(
        select(CompetitorPost.competitor_id, CompetitorPost.posted_at, CompetitorPost.views)
        .where(CompetitorPost.posted_at >= start_utc, CompetitorPost.posted_at < end_utc)
    ).all()

    post_counts: dict[tuple[int, date], int] = defaultdict(int)
    view_totals: dict[tuple[int, date], int] = defaultdict(int)
    for cid, posted_at, views in rows:
        if posted_at is None:
            continue
        d = to_ist(posted_at).date()
        post_counts[(cid, d)] += 1
        view_totals[(cid, d)] += (views or 0)

    names = {cid: username for cid, username in comps}
    dates = list(_day_range(first_day, days))
    posting_rows = [
        {"date": d.isoformat(), **{names[cid]: post_counts.get((cid, d), 0) for cid, _ in comps}}
        for d in dates
    ]
    views_rows = [
        {"date": d.isoformat(), **{names[cid]: view_totals.get((cid, d), 0) for cid, _ in comps}}
        for d in dates
    ]
    return {
        "dates": [d.isoformat() for d in dates],
        "posting_trend": posting_rows,
        "views_trend": views_rows,
        "competitors": [{"id": cid, "name": username} for cid, username in comps],
    }