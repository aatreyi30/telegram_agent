"""Phase 2.0 -- ``engagement_score``, the single source of truth for "how well
did this post do, relative to THIS channel's own recent history".

Every consumer (OutcomeCollector's ``post_outcomes.engagement_score`` today,
and Phase 3's ``audience_affinity`` later) MUST call the functions here rather
than re-deriving the formula or the weights -- this is the one place they live
(Section 2.0 of upgrade.md).

Pure / deterministic. No AI, no writes -- this module never opens a write
transaction, it only reads.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Channel, Post, PostMetricSnapshot

# --------------------------------------------------------------------------- #
# Constants -- live ONLY here (Section 2.0). Nothing else should hardcode
# these weights/window; import them if a value is genuinely needed elsewhere.
# --------------------------------------------------------------------------- #
WINDOW_DAYS = 28
W_VIEWS, W_FORWARD, W_REACTION = 0.40, 0.35, 0.25

# nearest-snapshot matching for the 24h anchor (age_hours within +/-2h of 24)
_SNAPSHOT_TARGET_HOURS = 24.0
_SNAPSHOT_TOLERANCE_HOURS = 2.0


def _aware_utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on read-back; we always store UTC, so treat naive
    datetimes as UTC (mirrors the ``_aware`` helper in generation/revalidate.py
    and controllers/service.py -- kept local here so this module has no
    cross-layer import for one line)."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def pct(x: float, sorted_values: list[float]) -> float:
    """Percentile rank of ``x`` (0..1) within ``sorted_values``.

    Linear-rank definition: ``(count_below + 0.5 * count_equal) / n`` -- ties
    split at their midpoint so a value tied with the only sample in a size-1
    distribution scores 0.5 (neutral), not 0 or 1. An empty distribution also
    returns 0.5 (neutral -- never fabricate a high/low judgement from nothing).
    Sorts defensively so callers don't have to guarantee order.
    """
    if not sorted_values:
        return 0.5
    vals = sorted(sorted_values)
    n = len(vals)
    below = bisect_left(vals, x)
    equal = bisect_right(vals, x) - below
    return (below + 0.5 * equal) / n


def channel_distribution(s: Session, channel_id: int) -> dict:
    """Last-``WINDOW_DAYS``-day owned-post distributions of ``views_24h``,
    ``forward_rate``, ``reaction_rate`` for one channel.

    Read from ``posts`` joined to each post's nearest ~24h
    ``PostMetricSnapshot`` (``age_hours`` within +/-2h of 24; the single
    nearest one wins if more than one snapshot falls in that window). Returns
    sorted-ascending arrays, ready to hand to ``pct()``.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    post_ids = list(s.scalars(
        select(Post.id)
        .join(Channel, Channel.id == Post.channel_id)
        .where(Channel.kind == "owned", Post.channel_id == channel_id,
               Post.posted_at.isnot(None), Post.posted_at >= cutoff)
    ))
    if not post_ids:
        return {"views_24h": [], "forward_rate": [], "reaction_rate": []}

    lo = _SNAPSHOT_TARGET_HOURS - _SNAPSHOT_TOLERANCE_HOURS
    hi = _SNAPSHOT_TARGET_HOURS + _SNAPSHOT_TOLERANCE_HOURS
    snaps = s.scalars(
        select(PostMetricSnapshot).where(
            PostMetricSnapshot.post_id.in_(post_ids),
            PostMetricSnapshot.age_hours.isnot(None),
            PostMetricSnapshot.age_hours.between(lo, hi),
        )
    ).all()

    nearest: dict[int, PostMetricSnapshot] = {}
    for sn in snaps:
        cur = nearest.get(sn.post_id)
        if cur is None or abs(sn.age_hours - _SNAPSHOT_TARGET_HOURS) < abs(
            cur.age_hours - _SNAPSHOT_TARGET_HOURS
        ):
            nearest[sn.post_id] = sn

    views: list[float] = []
    forward_rate: list[float] = []
    reaction_rate: list[float] = []
    for sn in nearest.values():
        v = sn.views or 0
        views.append(v)
        forward_rate.append((sn.forwards or 0) / max(v, 1))
        reaction_rate.append((sn.reactions_total or 0) / max(v, 1))

    return {
        "views_24h": sorted(views),
        "forward_rate": sorted(forward_rate),
        "reaction_rate": sorted(reaction_rate),
    }


def engagement_score(
    views_24h: float, forward_rate: float, reaction_rate: float, distribution: dict
) -> float:
    """The single ``engagement_score`` formula (Section 2.0).

    Pure function -- the caller supplies this post's own 24h numbers (already
    computed) and its channel's distribution (from ``channel_distribution``);
    nothing here touches the DB.

        engagement_score = W_VIEWS * pct(views_24h)
                          + W_FORWARD * pct(forward_rate)
                          + W_REACTION * pct(reaction_rate)
    """
    p_views = pct(views_24h, distribution.get("views_24h") or [])
    p_fwd = pct(forward_rate, distribution.get("forward_rate") or [])
    p_rxn = pct(reaction_rate, distribution.get("reaction_rate") or [])
    return W_VIEWS * p_views + W_FORWARD * p_fwd + W_REACTION * p_rxn
