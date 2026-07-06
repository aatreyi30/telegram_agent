"""Time-window + sample-size labels — so every stat states what it's based on.

Owned history spans ~12 months (large n); competitor data is thin and recent
(small n, from t.me/s snapshots). Comparisons must name BOTH windows so the reader
knows they differ and can judge the confidence. These helpers produce one
consistent phrasing used across strategy rationale, insights, and charts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import Post
from src.db.models_normalization import NormalizedPost, SourceType

IST = timezone(timedelta(hours=5, minutes=30))


def _months(days: float) -> float:
    return round(days / 30.44, 1)


def owned_window(s: Session) -> dict:
    """Date range + post count of OWNED posts that carry a view figure."""
    q = (select(func.min(Post.posted_at), func.max(Post.posted_at), func.count(Post.id))
         .join(NormalizedPost, NormalizedPost.source_id == Post.id)
         .where(NormalizedPost.source_type == SourceType.OWNED, Post.views.isnot(None)))
    start, end, n = s.execute(q).one()
    days = ((end - start).days if start and end else 0)
    return {"source": "owned", "start": start, "end": end, "days": days,
            "months": _months(days), "n": int(n or 0)}


def competitor_window(s: Session, username: str | None = None) -> dict:
    """Date range + post count of competitor posts (from t.me/s snapshots)."""
    from src.db.models import Competitor, CompetitorPost

    q = select(func.min(CompetitorPost.posted_at), func.max(CompetitorPost.posted_at),
               func.count(CompetitorPost.id))
    if username:
        q = (q.join(Competitor, Competitor.id == CompetitorPost.competitor_id)
             .where(Competitor.username == username))
    start, end, n = s.execute(q).one()
    days = ((end - start).days if start and end else 0)
    return {"source": f"competitor:{username}" if username else "competitors",
            "start": start, "end": end, "days": days, "months": _months(days), "n": int(n or 0)}


def _fmt_date(d) -> str:
    return d.astimezone(IST).strftime("%Y-%m-%d") if d else "?"


def period_label(window: dict) -> str:
    """e.g. 'owned · last 12.0 mo (2025-07-03→2026-07-03) · n=6,334 posts'."""
    src = window.get("source", "data")
    span = f"{_fmt_date(window.get('start'))}→{_fmt_date(window.get('end'))}"
    months = window.get("months") or 0
    n = window.get("n") or 0
    return f"{src} · last {months} mo ({span}) · n={n:,} posts"


def sample_note(n: int | None, window_desc: str) -> str:
    """Compact '· n=408 · owned, last 12 mo' suffix for inline stats."""
    npart = f"n={n:,}" if n else "n=?"
    return f"{npart} · {window_desc}"
