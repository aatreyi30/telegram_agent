"""Task B (collect_data.py modernization) -- a historical self-eval of
``baseline_v1`` over already-posted OWNED posts, so prediction accuracy
becomes visible on ``/plan`` + the weekly retro without waiting weeks for the
live pipeline (``daily_planner`` -> ``publishing`` -> ``outcome_collector``)
to accumulate history one post at a time.

For every owned post in a window:
  1. Ensure a ``PostOutcome`` exists (created lazily from the post's latest
     observed counters -- reuses ``backfill_outcomes.outcome_fields_from_counters``,
     which itself defers to ``engagement.py`` for the actual formula; nothing
     here re-derives it).
  2. Predict ``baseline_v1`` for that post AS OF its own ``posted_at`` (Section
     "NO-LOOK-AHEAD" below) and persist it as a separate, clearly-labelled
     ``PostPrediction`` row (``model_version='baseline_v1_backtest'``) so it
     never collides with / overwrites a real live ``baseline_v1`` prediction
     for the same post.
  3. Compute ``err_views_24h`` on the outcome against THIS prediction.

Then ``build_weekly_retro`` runs for every IST week the window covers, so
MAPE/bias/adjustments show up immediately.

NO-LOOK-AHEAD (the correctness crux): ``prediction.predict(..., as_of=...)``
only reads training rows -- and subscriber snapshots -- strictly BEFORE the
post's own ``posted_at`` (``prediction._gather``/``_subscriber_scale``: the
post being predicted has ``posted_at == as_of``, which fails the strict `<`
bound). A post's own views can therefore never enter its own prediction's
training window. See ``tests/test_backtest.py`` for the direct proof.

Batched (``batch_size``) per Task C.5 -- posts are scored in chunks with a
``session.flush()+commit()`` per chunk so this never holds one giant
transaction or loads the whole ``posts`` table into memory. Two caches keep
the per-post work cheap without threading a bespoke cache into
``prediction.py`` (which Task C.5 explicitly asks to reuse, not fork):
  * ``merchant_by_post``/``cluster_by_post`` -- the (static, as_of-independent)
    ``NormalizedPost`` -> ``PostClassification`` join, fetched ONCE for the
    whole window instead of once per post (``prediction._gather`` would
    otherwise re-run an equivalent join on every single call).
  * ``_cached_predict`` -- coarsely memoizes ``predict(..., as_of=...)`` by
    rounding ``as_of`` down to the hour. Rounding DOWN can only shrink the
    training window (a stricter, never-looser upper bound), so this is always
    at least as conservative as the exact-timestamp call -- it cannot
    introduce leakage, only (rarely) drop a same-hour sibling post from the
    training pool.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Channel, Post
from src.db.models_classification import PostClassification
from src.db.models_normalization import NormalizedPost, SourceType
from src.db.models_prediction import PostOutcome, PostPrediction
from src.services.analytics.engagement import channel_distribution
from src.services.analytics.periods import to_ist
from src.services.analytics.prediction import day_class, hour_bucket, predict
from src.services.analytics.retro import build_weekly_retro
from src.logger import get_logger

logger = get_logger(__name__)

MODEL_VERSION = "baseline_v1_backtest"


def _week_starts(start_ist: date, end_ist: date) -> list[date]:
    """Every IST-Monday ``week_start`` whose week overlaps ``[start_ist,
    end_ist)``. ``end_ist`` is exclusive (mirrors the caller's half-open UTC
    window converted to IST calendar dates)."""
    if end_ist <= start_ist:
        return []
    first_monday = start_ist - timedelta(days=start_ist.weekday())
    last_day = end_ist - timedelta(days=1)
    weeks: list[date] = []
    d = first_monday
    while d <= last_day:
        weeks.append(d)
        d += timedelta(days=7)
    return weeks


def _cached_predict(s: Session, channel_id: int, features: dict, as_of: datetime, cache: dict) -> dict:
    """Coarse memo of ``prediction.predict(..., as_of=...)`` -- see module
    docstring for why flooring ``as_of`` to the hour is always safe."""
    hour_floor = as_of.replace(minute=0, second=0, microsecond=0)
    key = (
        channel_id,
        features["hour_bucket"],
        features["day_class"],
        features["post_type_cluster"],
        features["merchant_key"],
        hour_floor,
    )
    cached = cache.get(key)
    if cached is None:
        cached = predict(s, channel_id, features, as_of=hour_floor)
        cache[key] = cached
    return cached


def _score_one(
    s: Session,
    post: Post,
    merchant_by_post: dict,
    cluster_by_post: dict,
    dist_cache: dict,
    predict_cache: dict,
    counts: dict,
) -> None:
    # 1) outcome -- create lazily from latest observed counters if missing.
    # Reuses backfill_outcomes' pure counter->fields math (Task B.a) rather
    # than re-deriving the engagement formula; an existing outcome (e.g. the
    # live OutcomeCollector already scored this post) is left as-is.
    from scripts.backfill_outcomes import outcome_fields_from_counters

    outcome = s.get(PostOutcome, post.id)
    if outcome is None:
        if post.channel_id not in dist_cache:
            dist_cache[post.channel_id] = channel_distribution(s, post.channel_id)
        fields = outcome_fields_from_counters(
            post.views, post.forwards, post.reactions_total, dist_cache[post.channel_id]
        )
        outcome = PostOutcome(post_id=post.id, phase_1h_done=False, phase_6h_done=False,
                              phase_24h_done=True, **fields)
        s.add(outcome)
        counts["outcomes_created"] += 1
    else:
        counts["outcomes_existing"] += 1

    # 2) baseline_v1 prediction AS OF this post's own posted_at -- see
    # module docstring's NO-LOOK-AHEAD section.
    posted_at = post.posted_at
    when_ist = to_ist(posted_at)
    features = {
        "channel_id": post.channel_id,
        "hour_bucket": hour_bucket(when_ist.hour),
        "day_class": day_class(when_ist),
        "post_type_cluster": cluster_by_post.get(post.id),
        "merchant_key": merchant_by_post.get(post.id),
    }
    prediction = _cached_predict(s, post.channel_id, features, posted_at, predict_cache)
    features = {
        **features,
        "fallback_level": prediction["fallback_level"],
        "n_samples": prediction["n_samples"],
        "subscriber_scale": prediction["subscriber_scale"],
    }

    pred_row = s.scalar(
        select(PostPrediction).where(
            PostPrediction.post_id == post.id, PostPrediction.model_version == MODEL_VERSION
        )
    )
    if pred_row is None:
        pred_row = PostPrediction(post_id=post.id, model_version=MODEL_VERSION, features=features)
        s.add(pred_row)
    pred_row.predicted_views_1h = prediction["views_1h"]
    pred_row.predicted_views_6h = prediction["views_6h"]
    pred_row.predicted_views_24h = prediction["views_24h"]
    pred_row.predicted_forwards_24h = prediction["forwards_24h"]
    pred_row.features = features
    counts["predictions_written"] += 1

    # 3) err_views_24h -- against OUR OWN backtest prediction specifically
    # (never a live baseline_v1 that might also exist for this post).
    if outcome.views_24h is not None and prediction.get("views_24h"):
        outcome.err_views_24h = (outcome.views_24h - prediction["views_24h"]) / prediction["views_24h"]


def run_backtest(s: Session, start: datetime, end: datetime, batch_size: int = 200) -> dict:
    """Historical ``baseline_v1`` self-eval over owned posts with
    ``posted_at`` in ``[start, end)`` (UTC, half-open -- same convention as
    ``collect_data.py``'s export window). Populates a ``PostOutcome`` (where
    missing) and a ``baseline_v1_backtest`` ``PostPrediction`` per post, then
    builds a ``WeeklyRetro`` for every IST week the window touches.

    Batched via ``batch_size`` (Task C.5): posts are processed in chunks, each
    chunk flushed+committed before the next, so this never builds one giant
    transaction or holds the whole ``posts`` table in memory. Returns counts
    for the run summary (posts scanned/scored, predictions written, retros
    built).
    """
    post_ids = list(
        s.scalars(
            select(Post.id)
            .join(Channel, Channel.id == Post.channel_id)
            .where(Channel.kind == "owned", Post.posted_at.isnot(None),
                   Post.posted_at >= start, Post.posted_at < end)
            .order_by(Post.posted_at)
        )
    )
    counts = {
        "posts_scanned": len(post_ids),
        "outcomes_created": 0,
        "outcomes_existing": 0,
        "predictions_written": 0,
        "retros_built": 0,
    }
    if not post_ids:
        return counts

    # static, as_of-independent per-post facts -- fetched ONCE for the whole
    # window rather than re-joined inside the per-post prediction loop.
    norm_rows = s.execute(
        select(NormalizedPost.source_id, NormalizedPost.primary_merchant_key, PostClassification.cluster_id)
        .outerjoin(PostClassification, PostClassification.normalized_post_id == NormalizedPost.id)
        .where(NormalizedPost.source_type == SourceType.OWNED, NormalizedPost.source_id.in_(post_ids))
    ).all()
    merchant_by_post = {r[0]: r[1] for r in norm_rows}
    cluster_by_post = {r[0]: r[2] for r in norm_rows}

    dist_cache: dict[int, dict] = {}
    predict_cache: dict[tuple, dict] = {}

    for chunk_start in range(0, len(post_ids), batch_size):
        chunk_ids = post_ids[chunk_start: chunk_start + batch_size]
        posts = list(s.scalars(select(Post).where(Post.id.in_(chunk_ids)).order_by(Post.posted_at)))
        for post in posts:
            _score_one(s, post, merchant_by_post, cluster_by_post, dist_cache, predict_cache, counts)
        s.flush()
        s.commit()  # commit-sized chunk (Task C.5) -- never one giant transaction
        logger.info("[backtest] scored %d/%d post(s)", min(chunk_start + batch_size, len(post_ids)),
                    len(post_ids))

    start_ist = to_ist(start).date()
    end_ist = to_ist(end).date()
    for week_start in _week_starts(start_ist, end_ist):
        build_weekly_retro(s, week_start)
        counts["retros_built"] += 1
    s.commit()

    return counts
