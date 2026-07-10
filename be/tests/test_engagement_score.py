"""Phase 2.0 tests -- engagement_score percentile math, weights, and the
channel_distribution DB read (nearest ~24h snapshot per post)."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/eng.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db

    init_db()
    yield


def test_pct_empty_distribution_is_neutral():
    from src.services.analytics.engagement import pct

    assert pct(100, []) == 0.5


def test_pct_linear_rank():
    from src.services.analytics.engagement import pct

    vals = [10, 20, 30, 40, 50]
    assert pct(10, vals) == pytest.approx(0.1)   # 0 below, 1 equal -> (0+0.5)/5
    assert pct(50, vals) == pytest.approx(0.9)   # 4 below, 1 equal -> (4+0.5)/5
    assert pct(25, vals) == pytest.approx(0.4)   # 2 below, 0 equal -> 2/5


def test_pct_ties_split_at_midpoint():
    from src.services.analytics.engagement import pct

    assert pct(10, [10, 10, 10]) == pytest.approx(0.5)


def test_pct_sorts_defensively():
    from src.services.analytics.engagement import pct

    assert pct(25, [50, 10, 40, 20, 30]) == pytest.approx(0.4)


def test_engagement_score_weights_sum_to_one():
    from src.services.analytics.engagement import W_FORWARD, W_REACTION, W_VIEWS

    assert W_VIEWS + W_FORWARD + W_REACTION == pytest.approx(1.0)


def test_engagement_score_top_and_bottom_of_distribution():
    from src.services.analytics.engagement import engagement_score

    dist = {
        "views_24h": [100, 200, 300, 400, 500],
        "forward_rate": [0.01, 0.02, 0.03, 0.04, 0.05],
        "reaction_rate": [0.001, 0.002, 0.003, 0.004, 0.005],
    }
    top = engagement_score(500, 0.05, 0.005, dist)
    bottom = engagement_score(100, 0.01, 0.001, dist)
    assert top == pytest.approx(0.9)
    assert bottom == pytest.approx(0.1)
    assert bottom < top


def test_channel_distribution_uses_nearest_24h_snapshot():
    from src.db.models import Channel, Post, PostMetricSnapshot
    from src.db.session import session_scope
    from src.services.analytics.engagement import channel_distribution

    with session_scope() as s:
        ch = Channel(tg_channel_id=101, username="edist", title="E")
        s.add(ch)
        s.flush()
        base = datetime.now(timezone.utc) - timedelta(days=2)
        views_at_24h = [100, 150, 200]
        for i, v in enumerate(views_at_24h):
            p = Post(channel_id=ch.id, tg_message_id=i, posted_at=base - timedelta(hours=i),
                     collected_at=base, views=v, forwards=1, reactions_total=1)
            s.add(p)
            s.flush()
            # a snapshot far from the 24h anchor -- must be ignored
            s.add(PostMetricSnapshot(post_id=p.id, captured_at=base, age_hours=1.0,
                                     views=10, forwards=0, reactions_total=0))
            # the nearest-to-24h snapshot -- must win
            s.add(PostMetricSnapshot(post_id=p.id, captured_at=base, age_hours=24.2,
                                     views=v, forwards=2, reactions_total=1))
        s.flush()
        channel_id = ch.id

    with session_scope() as s:
        dist = channel_distribution(s, channel_id)

    assert sorted(dist["views_24h"]) == sorted(views_at_24h)
    assert len(dist["forward_rate"]) == 3
    assert len(dist["reaction_rate"]) == 3


def test_channel_distribution_empty_when_no_history():
    from src.db.models import Channel
    from src.db.session import session_scope
    from src.services.analytics.engagement import channel_distribution

    with session_scope() as s:
        ch = Channel(tg_channel_id=102, username="ekempty", title="Empty")
        s.add(ch)
        s.flush()
        channel_id = ch.id

    with session_scope() as s:
        dist = channel_distribution(s, channel_id)

    assert dist == {"views_24h": [], "forward_rate": [], "reaction_rate": []}
