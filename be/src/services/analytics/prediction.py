"""Phase 2.2 -- ``baseline_v1``, a deterministic median-lookup predictor.

No ML model, no training step: for a given feature cell (posting hour bucket,
weekday/weekend, learned post-type cluster, merchant), predict this channel's
own historical median ``views_24h`` (and forward rate), falling back to a
coarser cell whenever the exact cell has too few samples. Scaled for
subscriber drift so a channel that's grown since those historical posts isn't
under-predicted.

Two entry points wire this into the pipeline (Section 2.2 design note):
  * ``predict_for_slot`` -- called from ``jit_fill.fill_due_slots`` when a draft is
    queued (no real post yet, so ``post_type_cluster`` is unknown -- see the
    docstring on ``predict_for_slot``).
  * ``repredict_and_link_on_publish`` -- called from
    ``publishing.Publisher.publish`` at send time; re-predicts with fresh
    data and best-effort links the ``PostPrediction`` to the real ``post_id``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Channel, Post, PostMetricSnapshot
from src.db.models_classification import PostClassification
from src.db.models_growth_snapshot import ParticipantSnapshot
from src.db.models_normalization import NormalizedPost, SourceType
from src.db.session import session_scope
from src.services.analytics.periods import to_ist
from src.logger import get_logger

logger = get_logger(__name__)

MODEL_VERSION = "baseline_v1"
WINDOW_DAYS = 28
MIN_SAMPLES = 5  # a cell needs at least this many historical posts to be trusted

# nearest-snapshot matching per horizon: (target_hours, tolerance_hours)
_HORIZON_1H = (1.0, 0.75)
_HORIZON_6H = (6.0, 2.0)
_HORIZON_24H = (24.0, 2.0)


def _aware_utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on read-back; we always store UTC, so treat naive
    datetimes as UTC (mirrors ``generation/revalidate.py::_aware``)."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def hour_bucket(hour: int) -> str:
    """3-hour IST bucket label: 0-2, 3-5, ..., 21-23."""
    lo = (hour // 3) * 3
    return f"{lo:02d}-{lo + 2:02d}"


def day_class(dt_ist: datetime) -> str:
    """'weekend' (Sat/Sun) or 'weekday', from an IST-aware datetime."""
    return "weekend" if dt_ist.weekday() >= 5 else "weekday"


def dominant_merchant_key(deals: Sequence[object]) -> str | None:
    """Most common ``merchant_key`` among a batch of already-loaded
    ``EnrichedDeal``-like objects, or ``None`` if none carry one. Used to pick
    the ``merchant_key`` feature for a not-yet-posted collection draft."""
    keys = [getattr(d, "merchant_key", None) for d in deals]
    keys = [k for k in keys if k]
    if not keys:
        return None
    return Counter(keys).most_common(1)[0][0]


def _merchant_key_for_deal_ids(s: Session, deal_ids: list[str]) -> str | None:
    """Same as ``dominant_merchant_key`` but for callers that only have
    ``EnrichedDeal.deal_id`` strings (e.g. ``GeneratedPost.deal_ids``)."""
    if not deal_ids:
        return None
    from src.db.models_generation import EnrichedDeal

    keys = [
        k
        for k in s.scalars(
            select(EnrichedDeal.merchant_key).where(EnrichedDeal.deal_id.in_(deal_ids))
        )
        if k
    ]
    if not keys:
        return None
    return Counter(keys).most_common(1)[0][0]


def _nearest(snaps: list[PostMetricSnapshot], target: float, tol: float) -> PostMetricSnapshot | None:
    cands = [sn for sn in snaps if sn.age_hours is not None and abs(sn.age_hours - target) <= tol]
    if not cands:
        return None
    return min(cands, key=lambda sn: abs(sn.age_hours - target))


def _gather(s: Session, channel_id: int, as_of: datetime | None = None) -> list[dict]:
    """One row per owned post in the last ``WINDOW_DAYS`` with a usable ~24h
    snapshot: feature-cell fields + views_1h/6h/24h + forward_rate.

    ``as_of`` (default ``None`` -- today's live behaviour, unchanged) bounds
    the training window to strictly BEFORE that instant when given (Phase 2
    backtest, ``backtest.py``): ``posted_at >= as_of - WINDOW_DAYS`` AND
    ``posted_at < as_of``. That upper bound is the no-look-ahead guarantee --
    it excludes the very post being predicted (whose own ``posted_at`` equals
    ``as_of``) and every post after it, so a post's own outcome can never leak
    into its own prediction's training data. When ``as_of`` is ``None`` there
    is no upper bound at all (identical query to before this parameter
    existed) -- live posts never have a future ``posted_at`` anyway, so this
    is a no-op there, not just an equivalent one.
    """
    reference = as_of if as_of is not None else datetime.now(timezone.utc)
    cutoff = reference - timedelta(days=WINDOW_DAYS)
    conditions = [
        Channel.kind == "owned",
        Post.channel_id == channel_id,
        Post.posted_at.isnot(None),
        Post.posted_at >= cutoff,
    ]
    if as_of is not None:
        conditions.append(Post.posted_at < as_of)
    posts = s.execute(
        select(Post.id, Post.posted_at)
        .join(Channel, Channel.id == Post.channel_id)
        .where(*conditions)
    ).all()
    if not posts:
        return []
    post_ids = [p[0] for p in posts]
    posted_at = {p[0]: _aware_utc(p[1]) for p in posts}

    snaps = s.scalars(
        select(PostMetricSnapshot).where(
            PostMetricSnapshot.post_id.in_(post_ids),
            PostMetricSnapshot.age_hours.isnot(None),
        )
    ).all()
    by_post: dict[int, list[PostMetricSnapshot]] = defaultdict(list)
    for sn in snaps:
        by_post[sn.post_id].append(sn)

    # post_type_cluster / merchant_key via NormalizedPost -> PostClassification
    norm_rows = s.execute(
        select(NormalizedPost.source_id, NormalizedPost.primary_merchant_key, PostClassification.cluster_id)
        .outerjoin(PostClassification, PostClassification.normalized_post_id == NormalizedPost.id)
        .where(NormalizedPost.source_type == SourceType.OWNED, NormalizedPost.source_id.in_(post_ids))
    ).all()
    cluster_by_post = {r[0]: r[2] for r in norm_rows}
    merchant_by_post = {r[0]: r[1] for r in norm_rows}

    rows: list[dict] = []
    for pid in post_ids:
        pat = posted_at.get(pid)
        if pat is None:
            continue
        post_snaps = by_post.get(pid, [])
        snap24 = _nearest(post_snaps, *_HORIZON_24H)
        if snap24 is None or not snap24.views:
            continue  # no usable 24h anchor -> can't contribute to the lookup
        snap1 = _nearest(post_snaps, *_HORIZON_1H)
        snap6 = _nearest(post_snaps, *_HORIZON_6H)
        pat_ist = to_ist(pat)
        rows.append(
            {
                "hour_bucket": hour_bucket(pat_ist.hour),
                "day_class": day_class(pat_ist),
                "cluster_id": cluster_by_post.get(pid),
                "merchant_key": merchant_by_post.get(pid),
                "views_24h": snap24.views,
                "views_1h": snap1.views if snap1 else None,
                "views_6h": snap6.views if snap6 else None,
                "forward_rate": (snap24.forwards or 0) / max(snap24.views, 1),
            }
        )
    return rows


def _lookup(rows: list[dict], hb: str | None, dc: str | None, cluster: int | None, merchant: str | None):
    """Fallback hierarchy (Section 2.2, exact order):
    1. (hour_bucket, day_class, post_type_cluster, merchant_key)
    2. <5 samples -> drop merchant_key
    3. <5 samples -> drop post_type_cluster -> (hour_bucket, day_class)
    4. <5 samples -> channel median (every post in the window, no filter)
    Returns (matching_rows, fallback_level_label).
    """
    if not rows:
        return [], "no_data"

    def cell1(r: dict) -> bool:
        return (
            r["hour_bucket"] == hb
            and r["day_class"] == dc
            and r["cluster_id"] == cluster
            and r["merchant_key"] == merchant
        )

    def cell2(r: dict) -> bool:
        return r["hour_bucket"] == hb and r["day_class"] == dc and r["cluster_id"] == cluster

    def cell3(r: dict) -> bool:
        return r["hour_bucket"] == hb and r["day_class"] == dc

    for pred, label in (
        (cell1, "hour_day_cluster_merchant"),
        (cell2, "hour_day_cluster"),
        (cell3, "hour_day"),
    ):
        matches = [r for r in rows if pred(r)]
        if len(matches) >= MIN_SAMPLES:
            return matches, label
    return rows, "channel_median"


def _subscriber_scale(s: Session, channel_id: int, as_of: datetime | None = None) -> float:
    """current_subs / median_subs_of_window -- scales the historical median up
    (or down) for a channel that has grown (or shrunk) since. 1.0 (no-op) if
    there's no subscriber snapshot history to scale against.

    ``as_of`` (default ``None``, unchanged live behaviour) makes "current"
    mean "as of that instant" for a backtest: only snapshots captured strictly
    before/at ``as_of`` count, and the "current" reading is the most recent one
    at or before ``as_of`` -- never a snapshot from after the post being
    predicted. No upper bound is applied when ``as_of`` is ``None`` (identical
    query to before this parameter existed).
    """
    reference = as_of if as_of is not None else datetime.now(timezone.utc)
    cutoff = reference - timedelta(days=WINDOW_DAYS)
    conditions = [ParticipantSnapshot.channel_id == channel_id, ParticipantSnapshot.captured_at >= cutoff]
    if as_of is not None:
        conditions.append(ParticipantSnapshot.captured_at <= as_of)
    rows = s.execute(
        select(ParticipantSnapshot.captured_at, ParticipantSnapshot.count)
        .where(*conditions)
        .order_by(ParticipantSnapshot.captured_at)
    ).all()
    counts = [r[1] for r in rows if r[1]]
    if not counts:
        return 1.0
    med = median(counts)
    if not med:
        return 1.0
    current = counts[-1]  # most recent observation in the window (rows ordered ascending)
    return current / med


def predict(s: Session, channel_id: int, features: dict, *, as_of: datetime | None = None) -> dict:
    """Pure lookup with fallback hierarchy. ``features`` carries
    ``hour_bucket``, ``day_class``, ``post_type_cluster``, ``merchant_key``.

    ``as_of`` (default ``None``) is the no-look-ahead knob for backtesting
    (Phase 2 self-eval, ``services/analytics/backtest.py``): when given, both
    the cell-median lookup (``_gather``) and the subscriber-drift scaling
    (``_subscriber_scale``) only see data strictly before that instant, so a
    post's own outcome can never enter its own prediction's training window.
    Leaving it ``None`` (every existing call site -- ``daily_planner.py``,
    ``publishing.py``) preserves today's live "last 28 days from now" behaviour
    exactly, byte-for-byte -- see ``test_prediction_baseline.py`` /
    ``test_backtest.py::test_as_of_none_matches_live_behavior``.

    Returns ``{views_1h, views_6h, views_24h, forwards_24h}`` (any of them
    ``None`` when there's genuinely no decay-ratio/forward-rate history to
    derive it from -- never fabricated) plus diagnostic
    ``fallback_level``/``n_samples``/``subscriber_scale`` for transparency.
    """
    hb = features.get("hour_bucket")
    dc = features.get("day_class")
    cluster = features.get("post_type_cluster")
    merchant = features.get("merchant_key")

    rows = _gather(s, channel_id, as_of=as_of)
    matches, level = _lookup(rows, hb, dc, cluster, merchant)
    if not matches:
        return {
            "views_1h": None,
            "views_6h": None,
            "views_24h": None,
            "forwards_24h": None,
            "fallback_level": "no_data",
            "n_samples": 0,
            "subscriber_scale": 1.0,
        }

    med_views = median([r["views_24h"] for r in matches])
    med_fwd_rate = median([r["forward_rate"] for r in matches])
    scale = _subscriber_scale(s, channel_id, as_of=as_of)
    predicted_24h = med_views * scale

    # channel-wide decay ratios (not cell-scoped -- Section 2.2)
    r1 = [r["views_1h"] / r["views_24h"] for r in rows if r.get("views_1h") is not None and r["views_24h"]]
    r6 = [r["views_6h"] / r["views_24h"] for r in rows if r.get("views_6h") is not None and r["views_24h"]]
    ratio_1h = median(r1) if r1 else None
    ratio_6h = median(r6) if r6 else None

    return {
        "views_1h": round(predicted_24h * ratio_1h) if ratio_1h is not None else None,
        "views_6h": round(predicted_24h * ratio_6h) if ratio_6h is not None else None,
        "views_24h": round(predicted_24h),
        "forwards_24h": round(predicted_24h * med_fwd_rate) if med_fwd_rate is not None else None,
        "fallback_level": level,
        "n_samples": len(matches),
        "subscriber_scale": round(scale, 4),
    }


def predict_for_slot(
    s: Session,
    channel_id: int,
    scheduled_at_utc: datetime,
    *,
    merchant_key: str | None = None,
    post_type_cluster: int | None = None,
    as_of: datetime | None = None,
) -> tuple[dict, dict]:
    """Build the feature cell for a not-yet-posted draft scheduled at
    ``scheduled_at_utc`` and return ``(features, prediction)`` -- the shapes
    ``PostPrediction.features``/``predicted_*`` expect.

    ``post_type_cluster`` is unknown for a draft (classification runs on
    already-normalized owned Posts, which don't exist until after the post is
    actually sent and re-collected) -- callers pass ``None`` unless/until a
    pre-send classifier exists; the fallback hierarchy in ``predict()``
    handles that gracefully by dropping it first.

    ``as_of`` (default ``None``, unchanged) is forwarded to ``predict()`` for
    the backtest no-look-ahead knob; live callers never pass it.
    """
    when_ist = to_ist(scheduled_at_utc)
    features = {
        "channel_id": channel_id,
        "hour_bucket": hour_bucket(when_ist.hour),
        "day_class": day_class(when_ist),
        "post_type_cluster": post_type_cluster,
        "merchant_key": merchant_key,
    }
    prediction = predict(s, channel_id, features, as_of=as_of)
    features["fallback_level"] = prediction["fallback_level"]
    features["n_samples"] = prediction["n_samples"]
    features["subscriber_scale"] = prediction["subscriber_scale"]
    return features, prediction


def repredict_and_link_on_publish(generated_post_id: int, channel_ref: str) -> None:
    """Phase 2.2 publish-time hook (called from
    ``publishing.Publisher.publish`` right after a send resolves ``ok``).

    Re-predicts with fresh data (current subscriber count, latest historical
    medians) and writes/updates the ``PostPrediction`` row for this draft.
    Also best-effort links ``post_id`` by content hash -- this rarely
    succeeds *synchronously* today because the raw ``Post`` row is only
    created by the next ``telegram_sync`` poll, not by the send itself; it's
    still correct to attempt (and cheap), and it starts succeeding the moment
    a sync happens to run before this hook, with no further code change.
    """
    from src.db.models import Channel, Post
    from src.db.models_generation import GeneratedPost
    from src.db.models_prediction import PostPrediction
    from src.services.collection.util import content_hash, extract_urls

    with session_scope() as s:
        gp = s.get(GeneratedPost, generated_post_id)
        if gp is None:
            return
        channel_row = s.get(Channel, gp.channel_id) if gp.channel_id else None
        if channel_row is None:
            channel_row = s.scalar(
                select(Channel).where(Channel.kind == "owned", Channel.username == channel_ref.lstrip("@"))
            )
        if channel_row is None:
            logger.info("[prediction] publish hook: could not resolve a channel for #%s", generated_post_id)
            return

        merchant_key = _merchant_key_for_deal_ids(s, gp.deal_ids or [])
        features, prediction = predict_for_slot(
            s, channel_row.id, datetime.now(timezone.utc), merchant_key=merchant_key
        )

        # same hash the owned collector computes on ingest (text, extracted links, media_type)
        digest = content_hash(gp.rendered_text, extract_urls(gp.rendered_text), None)
        matched_post_id = s.scalar(
            select(Post.id).where(Post.channel_id == channel_row.id, Post.content_sha256 == digest)
        )

        existing = s.scalar(
            select(PostPrediction).where(PostPrediction.generated_post_id == generated_post_id)
        )
        if existing is None:
            existing = PostPrediction(
                generated_post_id=generated_post_id, model_version=MODEL_VERSION, features=features
            )
            s.add(existing)
        existing.predicted_views_1h = prediction["views_1h"]
        existing.predicted_views_6h = prediction["views_6h"]
        existing.predicted_views_24h = prediction["views_24h"]
        existing.predicted_forwards_24h = prediction["forwards_24h"]
        existing.model_version = MODEL_VERSION
        existing.features = features
        if matched_post_id is not None:
            existing.post_id = matched_post_id
