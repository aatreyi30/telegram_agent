"""Phase 2.3 tests -- OutcomeCollector: snapshot-horizon selection, 24h
completion, and scoring posts with and without a linked PostPrediction."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/outc.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db

    init_db()
    yield


def _channel(s, tg_id, username):
    from src.db.models import Channel

    ch = Channel(tg_channel_id=tg_id, username=username, title=username)
    s.add(ch)
    s.flush()
    return ch


def _post(s, channel_id, msg_id, posted_at):
    from src.db.models import Post

    p = Post(channel_id=channel_id, tg_message_id=msg_id, posted_at=posted_at, collected_at=posted_at)
    s.add(p)
    s.flush()
    return p


def _snap(s, post_id, captured_at, age_hours, views, forwards=0, reactions=0):
    from src.db.models import PostMetricSnapshot

    s.add(PostMetricSnapshot(post_id=post_id, captured_at=captured_at, age_hours=age_hours,
                             views=views, forwards=forwards, reactions_total=reactions))


def test_collect_due_outcomes_creates_and_completes_all_phases():
    from src.db.models_prediction import PostOutcome
    from src.db.session import session_scope
    from src.services.analytics.outcomes import collect_due_outcomes

    now = datetime.now(timezone.utc)
    posted_at = now - timedelta(hours=25)  # 1h, 6h, and 24h are all due

    with session_scope() as s:
        ch = _channel(s, 301, "outc1")
        p = _post(s, ch.id, 1, posted_at)
        _snap(s, p.id, posted_at + timedelta(hours=1), 1.0, views=50, forwards=1, reactions=0)
        _snap(s, p.id, posted_at + timedelta(hours=6), 6.0, views=300, forwards=5, reactions=1)
        _snap(s, p.id, posted_at + timedelta(hours=24), 24.0, views=1000, forwards=20, reactions=10)
        s.flush()
        post_id = p.id

    with session_scope() as s:
        n = collect_due_outcomes(s)
    assert n == 1

    with session_scope() as s:
        outcome = s.get(PostOutcome, post_id)
        assert outcome.phase_1h_done and outcome.phase_6h_done and outcome.phase_24h_done
        assert outcome.views_1h == 50
        assert outcome.views_6h == 300
        assert outcome.views_24h == 1000
        assert outcome.forwards_24h == 20
        assert outcome.reactions_24h == 10
        assert outcome.forward_rate == pytest.approx(0.02)
        assert outcome.reaction_rate == pytest.approx(0.01)
        assert outcome.engagement_score is not None
        assert outcome.err_views_24h is None  # no PostPrediction linked -> honestly null


def test_collect_due_outcomes_ignores_snapshot_outside_tolerance():
    """A snapshot at age_hours=3 must NOT satisfy the 1h phase (tolerance is +/-45min)."""
    from src.db.models_prediction import PostOutcome
    from src.db.session import session_scope
    from src.services.analytics.outcomes import collect_due_outcomes

    now = datetime.now(timezone.utc)
    posted_at = now - timedelta(hours=25)

    with session_scope() as s:
        ch = _channel(s, 305, "outc5")
        p = _post(s, ch.id, 5, posted_at)
        _snap(s, p.id, posted_at + timedelta(hours=3), 3.0, views=999)     # too far from 1h target
        _snap(s, p.id, posted_at + timedelta(hours=24), 24.0, views=1000)  # satisfies 24h
        s.flush()
        post_id = p.id

    with session_scope() as s:
        collect_due_outcomes(s)

    with session_scope() as s:
        outcome = s.get(PostOutcome, post_id)
        assert outcome.phase_24h_done
        assert outcome.views_24h == 1000
        assert outcome.views_1h is None  # the 3h snapshot must not have been used


def test_collect_due_outcomes_computes_err_views_when_prediction_linked():
    from src.db.models_prediction import PostOutcome, PostPrediction
    from src.db.session import session_scope
    from src.services.analytics.outcomes import collect_due_outcomes

    now = datetime.now(timezone.utc)
    posted_at = now - timedelta(hours=25)

    with session_scope() as s:
        ch = _channel(s, 302, "outc2")
        p = _post(s, ch.id, 2, posted_at)
        _snap(s, p.id, posted_at + timedelta(hours=24), 24.0, views=1200, forwards=10, reactions=5)
        s.add(PostPrediction(post_id=p.id, predicted_views_24h=1000, model_version="baseline_v1", features={}))
        s.flush()
        post_id = p.id

    with session_scope() as s:
        collect_due_outcomes(s)

    with session_scope() as s:
        outcome = s.get(PostOutcome, post_id)
        assert outcome.phase_24h_done
        assert outcome.err_views_24h == pytest.approx((1200 - 1000) / 1000)


def test_collect_due_outcomes_leaves_phase_pending_without_snapshot():
    from src.db.models_prediction import PostOutcome
    from src.db.session import session_scope
    from src.services.analytics.outcomes import collect_due_outcomes

    now = datetime.now(timezone.utc)
    posted_at = now - timedelta(hours=2)  # only the 1h phase is due; no snapshot exists yet

    with session_scope() as s:
        ch = _channel(s, 303, "outc3")
        p = _post(s, ch.id, 3, posted_at)
        s.flush()
        post_id = p.id

    with session_scope() as s:
        collect_due_outcomes(s)

    with session_scope() as s:
        outcome = s.get(PostOutcome, post_id)
        assert outcome is not None       # row created lazily even though nothing completed yet
        assert not outcome.phase_1h_done


def test_collect_due_outcomes_gives_up_after_grace_period():
    from src.db.models_prediction import PostOutcome
    from src.db.session import session_scope
    from src.services.analytics.outcomes import collect_due_outcomes

    now = datetime.now(timezone.utc)
    posted_at = now - timedelta(hours=50)  # long past every horizon + its give-up grace period

    with session_scope() as s:
        ch = _channel(s, 304, "outc4")
        p = _post(s, ch.id, 4, posted_at)
        s.flush()
        post_id = p.id

    with session_scope() as s:
        collect_due_outcomes(s)

    with session_scope() as s:
        outcome = s.get(PostOutcome, post_id)
        assert outcome.phase_1h_done   # gave up honestly rather than retrying forever
        assert outcome.views_1h is None


def test_collect_due_outcomes_scores_posts_without_any_prediction():
    """The design point of 2.3: every owned post gets scored, prediction or not."""
    from src.db.models_prediction import PostOutcome, PostPrediction
    from src.db.session import session_scope
    from src.services.analytics.outcomes import collect_due_outcomes

    now = datetime.now(timezone.utc)
    posted_at = now - timedelta(hours=25)

    with session_scope() as s:
        ch = _channel(s, 306, "outc6")
        p = _post(s, ch.id, 6, posted_at)
        _snap(s, p.id, posted_at + timedelta(hours=24), 24.0, views=400, forwards=4, reactions=2)
        s.flush()
        post_id = p.id

    from sqlalchemy import func, select

    with session_scope() as s:
        collect_due_outcomes(s)
        assert s.scalar(
            select(func.count()).select_from(PostPrediction).where(PostPrediction.post_id == post_id)
        ) == 0

    with session_scope() as s:
        outcome = s.get(PostOutcome, post_id)
        assert outcome.phase_24h_done
        assert outcome.engagement_score is not None
        assert outcome.err_views_24h is None
