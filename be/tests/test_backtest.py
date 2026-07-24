"""Task B tests -- services/analytics/backtest.py (the historical baseline_v1
self-eval) and the `as_of` no-look-ahead parameter it depends on in
services/analytics/prediction.py. Mirrors the test_prediction_baseline.py /
test_weekly_retro.py style: an isolated tmp SQLite DB per module, pure-logic
assertions where possible, a couple of DB-backed unit checks, and one
end-to-end `run_backtest` run."""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timedelta, timezone

import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/backtest.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db

    init_db()
    yield


def _channel(s, tg_id, username, **kwargs):
    from src.db.models import Channel

    ch = Channel(tg_channel_id=tg_id, username=username, title=username, kind="owned", **kwargs)
    s.add(ch)
    s.flush()
    return ch


def _post(s, channel_id, msg_id, posted_at, views=None, forwards=None, reactions=None):
    from src.db.models import Post

    p = Post(channel_id=channel_id, tg_message_id=msg_id, posted_at=posted_at, collected_at=posted_at,
              views=views, forwards=forwards, reactions_total=reactions)
    s.add(p)
    s.flush()
    return p


def _snap(s, post_id, captured_at, age_hours, views, forwards=0, reactions=0):
    from src.db.models import PostMetricSnapshot

    s.add(PostMetricSnapshot(post_id=post_id, captured_at=captured_at, age_hours=age_hours,
                             views=views, forwards=forwards, reactions_total=reactions))


# --------------------------------------------------------------------------- #
# NO-LOOK-AHEAD -- the correctness crux (prediction.py's `as_of` parameter)
# --------------------------------------------------------------------------- #
def test_gather_excludes_the_post_being_predicted_at_its_own_as_of():
    """Direct proof: 5 historical posts (views=100, same cell) plus the post
    being predicted itself -- posted exactly at `as_of`, with an extreme
    views_24h that would obviously skew the median if it leaked in. It must
    not appear in `_gather`'s rows at all."""
    from src.db.session import session_scope
    from src.services.analytics.prediction import _gather

    with session_scope() as s:
        ch = _channel(s, 9001, "btgather1")
        channel_id = ch.id
        base = datetime.now(timezone.utc) - timedelta(days=5)
        for i, v in enumerate((100, 100, 100, 100, 100)):
            p = _post(s, channel_id, 1000 + i, base + timedelta(hours=i), views=v)
            _snap(s, p.id, p.posted_at + timedelta(hours=24), 24.0, v)
        # the post being predicted -- posted_at == as_of, an extreme outlier
        target = _post(s, channel_id, 2000, base + timedelta(hours=100), views=999_999)
        _snap(s, target.id, target.posted_at + timedelta(hours=24), 24.0, 999_999)
        s.flush()
        as_of = target.posted_at

    with session_scope() as s:
        rows = _gather(s, channel_id, as_of=as_of)

    assert len(rows) == 5  # the 6th (target) post excluded
    assert all(r["views_24h"] == 100 for r in rows)  # extreme outlier never leaked in


def test_gather_as_of_bounds_the_window_excludes_posts_after_it():
    """A post posted AFTER `as_of` (but still in the past relative to real
    "now") must also be excluded -- `as_of` bounds the window, it isn't just
    an alias for "up to now"."""
    from src.db.session import session_scope
    from src.services.analytics.prediction import _gather

    with session_scope() as s:
        ch = _channel(s, 9002, "btgather2")
        channel_id = ch.id
        base = datetime.now(timezone.utc) - timedelta(days=10)
        p_before = _post(s, channel_id, 3000, base, views=200)
        _snap(s, p_before.id, p_before.posted_at + timedelta(hours=24), 24.0, 200)
        as_of = base + timedelta(days=1)
        p_after = _post(s, channel_id, 3001, base + timedelta(days=2), views=888_888)
        _snap(s, p_after.id, p_after.posted_at + timedelta(hours=24), 24.0, 888_888)
        s.flush()

    with session_scope() as s:
        rows = _gather(s, channel_id, as_of=as_of)

    assert len(rows) == 1
    assert rows[0]["views_24h"] == 200


def test_subscriber_scale_as_of_ignores_snapshots_after_it():
    from src.db.models_growth_snapshot import ParticipantSnapshot
    from src.db.session import session_scope
    from src.services.analytics.prediction import _subscriber_scale

    with session_scope() as s:
        ch = _channel(s, 9004, "btscale1")
        channel_id = ch.id
        base = datetime.now(timezone.utc) - timedelta(days=10)
        s.add(ParticipantSnapshot(channel_id=channel_id, captured_at=base, count=1000))
        s.add(ParticipantSnapshot(channel_id=channel_id, captured_at=base + timedelta(days=1), count=1000))
        as_of = base + timedelta(days=2)
        # a snapshot AFTER as_of that would change the "current" reading if it leaked in
        s.add(ParticipantSnapshot(channel_id=channel_id, captured_at=base + timedelta(days=5), count=50_000))
        s.flush()

    with session_scope() as s:
        scale = _subscriber_scale(s, channel_id, as_of=as_of)

    assert scale == pytest.approx(1.0)  # "current" as of as_of is still 1000, not the future 50,000


def test_predict_as_of_none_matches_omitting_the_argument():
    """`as_of=None` (the explicit default) must behave identically to not
    passing the keyword at all -- every existing live call site
    (daily_planner.py, publishing.py) never passes it."""
    from src.db.models_growth_snapshot import ParticipantSnapshot
    from src.db.session import session_scope
    from src.services.analytics.periods import to_ist
    from src.services.analytics.prediction import day_class, hour_bucket, predict

    with session_scope() as s:
        ch = _channel(s, 9003, "btpredictnone")
        channel_id = ch.id
        base = (datetime.now(timezone.utc) - timedelta(days=5)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        for i, v in enumerate((100, 200, 300, 400, 500)):
            p = _post(s, channel_id, 4000 + i, base + timedelta(hours=i))
            _snap(s, p.id, p.posted_at + timedelta(hours=24), 24.0, v, forwards=int(v * 0.1))
        s.add(ParticipantSnapshot(channel_id=channel_id, captured_at=base, count=1000))
        s.flush()
        base_ist = to_ist(base)
        features = {"hour_bucket": hour_bucket(base_ist.hour), "day_class": day_class(base_ist),
                    "post_type_cluster": None, "merchant_key": None}

    with session_scope() as s:
        with_kwarg = predict(s, channel_id, features, as_of=None)
    with session_scope() as s:
        without_kwarg = predict(s, channel_id, features)

    assert with_kwarg == without_kwarg


# --------------------------------------------------------------------------- #
# run_backtest -- end-to-end
# --------------------------------------------------------------------------- #
def test_run_backtest_writes_predictions_outcomes_and_retro():
    from sqlalchemy import select

    from src.db.models_prediction import PostOutcome, PostPrediction, WeeklyRetro
    from src.db.session import session_scope
    from src.services.analytics.backtest import MODEL_VERSION, run_backtest

    anchor = date(2026, 2, 2)  # a Monday
    week_start = anchor - timedelta(days=anchor.weekday())
    start = datetime(week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc)
    end = start + timedelta(days=7)
    views_seq = [80, 120, 160, 200, 260, 320, 400, 500]  # 8 posts, spread across the week

    with session_scope() as s:
        # participants_count set explicitly (NULLs sort last in SQLite's DESC
        # order) so retro.py's `_owned_channel` deterministically resolves to
        # *this* channel in this module-scoped shared DB, not some other
        # test's channel above -- same convention as test_weekly_retro.py.
        ch = _channel(s, 9101, "btrun1", participants_count=999_999)
        channel_id = ch.id
        post_ids = []
        for i, v in enumerate(views_seq):
            posted_at = start + timedelta(hours=20 * i + 1)
            p = _post(s, channel_id, 5000 + i, posted_at, views=v, forwards=int(v * 0.05),
                      reactions=int(v * 0.02))
            # a ~24h snapshot -- prediction.py's `_gather` (the training-pool
            # builder) only picks up posts that have one; `Post.views` alone
            # (set above, used by the OUTCOME side) isn't enough on its own.
            _snap(s, p.id, posted_at + timedelta(hours=24), 24.0, v, forwards=int(v * 0.05),
                  reactions=int(v * 0.02))
            post_ids.append(p.id)
        s.flush()

    with session_scope() as s:
        # force multiple commit-sized batches (Task C.5) well under the total post count
        counts = run_backtest(s, start, end, batch_size=3)

    assert counts["posts_scanned"] == len(views_seq)
    assert counts["outcomes_created"] == len(views_seq)
    assert counts["outcomes_existing"] == 0
    assert counts["predictions_written"] == len(views_seq)
    assert counts["retros_built"] >= 1

    with session_scope() as s:
        preds = s.scalars(
            select(PostPrediction).where(PostPrediction.model_version == MODEL_VERSION)
        ).all()
        assert len(preds) == len(views_seq)
        assert all(p.post_id in post_ids for p in preds)
        assert all(p.features for p in preds)  # features populated, never empty

        outcomes = {o.post_id: o for o in s.scalars(
            select(PostOutcome).where(PostOutcome.post_id.in_(post_ids)))}
        assert len(outcomes) == len(views_seq)
        assert all(o.engagement_score is not None for o in outcomes.values())

        # every post except the very first (zero prior history -> "no_data",
        # no numeric prediction to diff against) gets a computed err_views_24h
        n_with_err = sum(1 for o in outcomes.values() if o.err_views_24h is not None)
        assert n_with_err == len(views_seq) - 1

        retro = s.scalar(select(WeeklyRetro).where(WeeklyRetro.week_start == week_start))
        assert retro is not None
        assert retro.metrics["prediction"]["n_posts"] == n_with_err


def test_run_backtest_is_idempotent_on_rerun():
    """Re-running over the same window must not duplicate PostPrediction rows
    (upsert-by-(post_id, model_version)) or WeeklyRetro rows (unique week_start)."""
    from sqlalchemy import func, select

    from src.db.models_prediction import PostPrediction, WeeklyRetro
    from src.db.session import session_scope
    from src.services.analytics.backtest import MODEL_VERSION, run_backtest

    anchor = date(2026, 2, 9)  # a Monday, distinct week from the test above
    week_start = anchor - timedelta(days=anchor.weekday())
    start = datetime(week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc)
    end = start + timedelta(days=7)

    with session_scope() as s:
        ch = _channel(s, 9103, "btidempotent")
        channel_id = ch.id
        post_ids = []
        for i, v in enumerate((100, 200, 300)):
            p = _post(s, channel_id, 7000 + i, start + timedelta(hours=10 * i + 1), views=v)
            post_ids.append(p.id)
        s.flush()

    with session_scope() as s:
        run_backtest(s, start, end, batch_size=200)
    with session_scope() as s:
        run_backtest(s, start, end, batch_size=200)  # rerun

    with session_scope() as s:
        n_preds = s.scalar(
            select(func.count()).select_from(PostPrediction).where(
                PostPrediction.model_version == MODEL_VERSION, PostPrediction.post_id.in_(post_ids)
            )
        )
        n_retros = s.scalar(
            select(func.count()).select_from(WeeklyRetro).where(WeeklyRetro.week_start == week_start)
        )
    assert n_preds == 3
    assert n_retros == 1


def test_run_backtest_predictions_never_see_a_later_posts_own_views():
    """End-to-end proof (not just `_gather` in isolation): the SECOND-TO-LAST
    post's own `baseline_v1_backtest` prediction must not be influenced by the
    LAST post's extreme views -- the last post is chronologically after it, so
    it can never enter that earlier post's training window."""
    from sqlalchemy import select

    from src.db.models_prediction import PostPrediction
    from src.db.session import session_scope
    from src.services.analytics.backtest import MODEL_VERSION, run_backtest

    anchor = date(2026, 2, 16)  # a Monday
    week_start = anchor - timedelta(days=anchor.weekday())
    start = datetime(week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc)
    end = start + timedelta(days=7)
    views_seq = [80, 120, 160, 200, 260, 320, 999_999_999]  # last post: extreme outlier

    with session_scope() as s:
        ch = _channel(s, 9102, "btrun2")
        channel_id = ch.id
        post_ids = []
        for i, v in enumerate(views_seq):
            posted_at = start + timedelta(hours=20 * i + 1)
            p = _post(s, channel_id, 6000 + i, posted_at, views=v)
            _snap(s, p.id, posted_at + timedelta(hours=24), 24.0, v)
            post_ids.append(p.id)
        s.flush()
        second_last_id = post_ids[-2]

    with session_scope() as s:
        run_backtest(s, start, end, batch_size=4)

    with session_scope() as s:
        pred = s.scalar(
            select(PostPrediction).where(
                PostPrediction.post_id == second_last_id, PostPrediction.model_version == MODEL_VERSION
            )
        )
        assert pred is not None
        # nowhere near the 999,999,999-view outlier that comes AFTER it chronologically
        assert pred.predicted_views_24h < 1000


def test_run_backtest_no_posts_in_window_is_a_noop():
    from datetime import date as date_type

    from src.db.session import session_scope
    from src.services.analytics.backtest import run_backtest

    anchor = date_type(2026, 2, 23)
    start = datetime(anchor.year, anchor.month, anchor.day, tzinfo=timezone.utc)
    end = start + timedelta(days=7)

    with session_scope() as s:
        counts = run_backtest(s, start, end, batch_size=50)

    assert counts == {
        "posts_scanned": 0, "outcomes_created": 0, "outcomes_existing": 0,
        "predictions_written": 0, "retros_built": 0,
    }
