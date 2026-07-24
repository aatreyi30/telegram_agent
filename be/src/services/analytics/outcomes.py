"""Phase 2.3 -- the OutcomeCollector.

Scores EVERY owned post (from ``posts`` + ``post_metric_snapshots``), whether
or not a ``PostPrediction`` exists and whether the post came from the
generation pipeline or was sent manually (Phase 2 design note in upgrade.md:
"prediction is best-effort per post; outcome/engagement is computed for
all posts"). ``err_views_24h``/the prediction link are simply null when no
prediction exists.

Runs as the ``outcome_collector`` job every 15 min (schedulers.py). Advances
each post through three phases (1h -> 6h -> 24h) as its snapshots become
available; ``engagement_score`` (single source of truth: ``engagement.py``)
and prediction error are only computed once, at the 24h phase.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from src.db.models import Channel, Post, PostMetricSnapshot
from src.db.models_prediction import PostOutcome, PostPrediction
from src.services.analytics.engagement import channel_distribution, engagement_score
from src.logger import get_logger

logger = get_logger(__name__)

# (phase key, target hours-since-posted, nearest-snapshot tolerance in hours)
# Tolerances MATCH prediction._HORIZON_* so the training path and the outcome/accuracy
# path anchor on the SAME snapshot for a given post. The 6h/24h tolerance was 0.75h,
# which — because stats_refresh doesn't reliably capture within ±0.75h of the 24h mark —
# made ~65% of posts give up with null 24h views (and disagreed with training's 2.0h).
_HORIZONS: tuple[tuple[str, float, float], ...] = (
    ("1h", 1.0, 0.75),
    ("6h", 6.0, 2.0),
    ("24h", 24.0, 2.0),
)
# if a phase is due but no snapshot ever lands within tolerance even after this
# much extra time, give up (mark done with nulls) rather than retry forever --
# stats_refresh only keeps writing snapshots for 30 days per post.
_GIVE_UP_EXTRA_HOURS = 24.0


def _aware_utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on read-back; we always store UTC, so treat naive
    datetimes as UTC (mirrors ``generation/revalidate.py::_aware``)."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _nearest_snapshot(
    s: Session, post_id: int, target_hours: float, tolerance_hours: float
) -> PostMetricSnapshot | None:
    rows = s.scalars(
        select(PostMetricSnapshot).where(
            PostMetricSnapshot.post_id == post_id,
            PostMetricSnapshot.age_hours.isnot(None),
            PostMetricSnapshot.age_hours.between(target_hours - tolerance_hours, target_hours + tolerance_hours),
        )
    ).all()
    if not rows:
        return None
    return min(rows, key=lambda r: abs(r.age_hours - target_hours))


def _finalize_24h(s: Session, outcome: PostOutcome, snap: PostMetricSnapshot, channel_id: int) -> None:
    views = snap.views or 0
    forwards = snap.forwards or 0
    reactions = snap.reactions_total or 0
    forward_rate = forwards / max(views, 1)
    reaction_rate = reactions / max(views, 1)

    outcome.forwards_24h = forwards
    outcome.reactions_24h = reactions
    outcome.forward_rate = forward_rate
    outcome.reaction_rate = reaction_rate
    outcome.engagement_score = engagement_score(
        views, forward_rate, reaction_rate, channel_distribution(s, channel_id)
    )

    pred = s.scalar(select(PostPrediction).where(PostPrediction.post_id == outcome.post_id))
    if pred is not None and pred.predicted_views_24h:
        outcome.err_views_24h = (views - pred.predicted_views_24h) / pred.predicted_views_24h


def collect_due_outcomes(s: Session) -> int:
    """Advance every owned post's ``PostOutcome`` through its due phases.

    Returns the number of posts whose outcome row changed this run (created
    and/or one or more phases advanced).

    Also runs the ``PostPrediction.post_id`` catch-up pass (G8): the publish-time
    hook (``prediction.repredict_and_link_on_publish``) usually can't link yet
    (its Post row doesn't exist at send time), so this job -- already running
    every 15 min -- re-attempts it each time, closing the loop the moment a
    published post's raw row shows up with no further code change needed.
    """
    from src.services.analytics.prediction import backfill_post_links

    linked = backfill_post_links(s)
    if linked:
        logger.info("[outcomes] linked %d post_prediction(s) to their published post", linked)

    now = datetime.now(timezone.utc)
    earliest_due_age = min(h[1] - h[2] for h in _HORIZONS)  # smallest (target - tolerance)

    OutcomeAlias = aliased(PostOutcome)
    rows = s.execute(
        select(Post.id, Post.posted_at, Post.channel_id)
        .join(Channel, Channel.id == Post.channel_id)
        .outerjoin(OutcomeAlias, OutcomeAlias.post_id == Post.id)
        .where(
            Channel.kind == "owned",
            Post.posted_at.isnot(None),
            Post.posted_at <= now - timedelta(hours=earliest_due_age),
            # any phase still incomplete -- not just 24h. A post can (rarely) finish
            # its 24h phase while an earlier phase never got a snapshot in tolerance
            # (e.g. stats_refresh missed the 6h window); checking 24h alone would
            # permanently stop revisiting that post's still-incomplete earlier phase.
            or_(
                OutcomeAlias.post_id.is_(None),
                OutcomeAlias.phase_1h_done.is_(False),
                OutcomeAlias.phase_6h_done.is_(False),
                OutcomeAlias.phase_24h_done.is_(False),
            ),
        )
    ).all()
    if not rows:
        return 0

    post_ids = [r[0] for r in rows]
    existing = {
        o.post_id: o
        for o in s.scalars(select(PostOutcome).where(PostOutcome.post_id.in_(post_ids)))
    }

    advanced = 0
    for pid, posted_at, channel_id in rows:
        pat = _aware_utc(posted_at)
        if pat is None:
            continue
        age_hours = (now - pat).total_seconds() / 3600.0

        outcome = existing.get(pid)
        if outcome is None:
            outcome = PostOutcome(post_id=pid)
            s.add(outcome)
            existing[pid] = outcome

        changed = False
        for phase, target, tol in _HORIZONS:
            done_attr = f"phase_{phase}_done"
            if getattr(outcome, done_attr):
                continue
            if age_hours < target - tol:
                continue  # not due yet

            snap = _nearest_snapshot(s, pid, target, tol)
            if snap is None:
                if age_hours < target + _GIVE_UP_EXTRA_HOURS:
                    continue  # keep waiting for a snapshot to land
                setattr(outcome, done_attr, True)  # give up honestly -- values stay null
                changed = True
                continue

            setattr(outcome, f"views_{phase}", snap.views)
            if phase == "24h":
                _finalize_24h(s, outcome, snap, channel_id)
            setattr(outcome, done_attr, True)
            changed = True

        if changed:
            advanced += 1

    return advanced
