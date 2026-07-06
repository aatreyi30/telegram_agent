"""Your channel vs competitors — comparison on the signals we can honestly measure.

Available for both sides: avg views/post, posts/day, posting-hour distribution
(posts/hour, IST), volume/activity, and the observation window + sample.

NOT available (labelled, never faked): reactions, forwards, reach, engagement-rate.
Your account is a channel *member* (no broadcast stats) and competitors come from the
public t.me/s preview (rounded views only). These need channel admin rights or a bot
in the channel — the dormant admin-stats collector fills them in once that exists.
"""

from __future__ import annotations

import statistics
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.services.analytics.periods import IST
from src.db.models import Competitor, CompetitorPost, Post
from src.db.models_normalization import NormalizedPost, SourceType

MIN_POSTS = 10
UNAVAILABLE = ["reactions", "forwards", "reach", "engagement_rate"]
_UNAVAILABLE_NOTE = ("Reactions, forwards, reach and engagement-rate need channel admin "
                     "rights (your channel) or a bot in the channel; competitor data is the "
                     "public t.me/s view count only. Shown as unavailable, never estimated.")


def _entity_stats(name: str, is_owned: bool, dated_views: list[tuple]) -> dict | None:
    """dated_views: list of (posted_at, views)."""
    dates = [d for d, _ in dated_views if d]
    if len(dates) < MIN_POSTS:
        return None
    views = [v for _, v in dated_views if v is not None]
    span_days = max((max(dates) - min(dates)).days, 0) + 1
    hours = Counter(d.astimezone(IST).hour for d in dates)
    return {
        "name": name, "is_owned": is_owned, "posts": len(dates),
        "window_days": span_days,
        "avg_views_per_post": round(statistics.fmean(views)) if views else None,
        "posts_per_day": round(len(dates) / span_days, 2),
        "posts_per_hour_ist": [hours.get(h, 0) for h in range(24)],
        # honest gaps
        "reactions": None, "forwards": None, "reach": None, "engagement_rate": None,
    }


def compare(s: Session, max_competitors: int = 6) -> dict:
    entities = []

    # owned
    owned_rows = s.execute(
        select(Post.posted_at, Post.views)
        .join(NormalizedPost, NormalizedPost.source_id == Post.id)
        .where(NormalizedPost.source_type == SourceType.OWNED, Post.posted_at.isnot(None))
    ).all()
    owned = _entity_stats("You (owned)", True, [(d, v) for d, v in owned_rows])
    if owned:
        entities.append(owned)

    # competitors (most posts first)
    comps = s.scalars(select(Competitor)).all()
    comp_stats = []
    for c in comps:
        rows = s.execute(
            select(CompetitorPost.posted_at, CompetitorPost.views)
            .where(CompetitorPost.competitor_id == c.id, CompetitorPost.posted_at.isnot(None))
        ).all()
        st = _entity_stats(c.username or c.title or f"comp{c.id}", False, [(d, v) for d, v in rows])
        if st:
            comp_stats.append(st)
    comp_stats.sort(key=lambda x: x["posts"], reverse=True)
    entities.extend(comp_stats[:max_competitors])

    return {
        "entities": entities,
        "unavailable": UNAVAILABLE,
        "note": _UNAVAILABLE_NOTE,
        "metrics": ["avg_views_per_post", "posts_per_day", "posts_per_hour_ist"],
    }
