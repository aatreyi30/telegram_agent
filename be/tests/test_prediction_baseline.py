"""Phase 2.2 tests -- baseline_v1: fallback hierarchy + subscriber scaling."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/pred.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db

    init_db()
    yield


def _row(hb="09-11", dc="weekday", cluster=1, merchant="amazon", views=100, fwd_rate=0.01):
    return {
        "hour_bucket": hb, "day_class": dc, "cluster_id": cluster, "merchant_key": merchant,
        "views_24h": views, "forward_rate": fwd_rate, "views_1h": None, "views_6h": None,
    }


# --------------------------------------------------------------------------- #
# _lookup -- pure fallback-hierarchy logic, no DB needed
# --------------------------------------------------------------------------- #
def test_lookup_full_cell_hit():
    from src.services.analytics.prediction import MIN_SAMPLES, _lookup

    rows = [_row(views=v) for v in (100, 200, 300, 400, 500)]
    matches, level = _lookup(rows, "09-11", "weekday", 1, "amazon")
    assert level == "hour_day_cluster_merchant"
    assert len(matches) == 5 >= MIN_SAMPLES


def test_lookup_drops_merchant_key_below_min_samples():
    from src.services.analytics.prediction import _lookup

    exact = [_row(merchant="amazon", views=v) for v in (100, 200, 300)]              # only 3 -> below MIN_SAMPLES
    other_merchant = [_row(merchant="flipkart", views=v) for v in (400, 500, 600)]   # same hour/day/cluster
    matches, level = _lookup(exact + other_merchant, "09-11", "weekday", 1, "amazon")
    assert level == "hour_day_cluster"
    assert len(matches) == 6


def test_lookup_drops_post_type_cluster_below_min_samples():
    from src.services.analytics.prediction import _lookup

    exact = [_row(cluster=1, merchant="amazon", views=v) for v in (100, 200)]
    other_cluster = [_row(cluster=2, merchant="flipkart", views=v) for v in (300, 400, 500)]
    matches, level = _lookup(exact + other_cluster, "09-11", "weekday", 1, "amazon")
    assert level == "hour_day"
    assert len(matches) == 5


def test_lookup_falls_back_to_channel_median():
    from src.services.analytics.prediction import _lookup

    rows = [_row(hb="18-20", dc="weekend", views=v) for v in (100, 200)]  # never matches the requested cell
    matches, level = _lookup(rows, "09-11", "weekday", 1, "amazon")
    assert level == "channel_median"
    assert len(matches) == 2  # all rows returned -- final catch-all, even below MIN_SAMPLES


def test_lookup_no_data():
    from src.services.analytics.prediction import _lookup

    matches, level = _lookup([], "09-11", "weekday", 1, "amazon")
    assert matches == [] and level == "no_data"


def test_hour_bucket_and_day_class():
    from src.services.analytics.prediction import day_class, hour_bucket

    assert hour_bucket(0) == "00-02"
    assert hour_bucket(9) == "09-11"
    assert hour_bucket(23) == "21-23"
    monday = datetime(2026, 7, 6, 10, tzinfo=timezone.utc)     # a Monday
    saturday = datetime(2026, 7, 11, 10, tzinfo=timezone.utc)  # a Saturday
    assert day_class(monday) == "weekday"
    assert day_class(saturday) == "weekend"


def test_dominant_merchant_key():
    from types import SimpleNamespace

    from src.services.analytics.prediction import dominant_merchant_key

    deals = [SimpleNamespace(merchant_key="amazon"), SimpleNamespace(merchant_key="amazon"),
             SimpleNamespace(merchant_key="flipkart"), SimpleNamespace(merchant_key=None)]
    assert dominant_merchant_key(deals) == "amazon"
    assert dominant_merchant_key([]) is None


# --------------------------------------------------------------------------- #
# predict() end-to-end -- DB-backed, including subscriber-drift scaling
# --------------------------------------------------------------------------- #
def _make_owned_post(s, channel_id, msg_id, posted_at, views_24h, forwards_24h):
    from src.db.models import Post, PostMetricSnapshot

    p = Post(channel_id=channel_id, tg_message_id=msg_id, posted_at=posted_at,
             collected_at=posted_at, views=views_24h)
    s.add(p)
    s.flush()
    s.add(PostMetricSnapshot(post_id=p.id, captured_at=posted_at + timedelta(hours=24),
                             age_hours=24.0, views=views_24h, forwards=forwards_24h, reactions_total=0))
    return p


def test_predict_end_to_end_with_subscriber_scaling():
    from src.db.models import Channel
    from src.db.models_growth_snapshot import ParticipantSnapshot
    from src.db.session import session_scope
    from src.services.analytics.periods import to_ist
    from src.services.analytics.prediction import day_class, hour_bucket, predict

    with session_scope() as s:
        ch = Channel(tg_channel_id=201, username="predch", title="P")
        s.add(ch)
        s.flush()
        channel_id = ch.id
        base = (datetime.now(timezone.utc) - timedelta(days=5)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        base_ist = to_ist(base)
        # 5 posts in the same hour-bucket/day-class cell; median views_24h = 300
        for i, v in enumerate((100, 200, 300, 400, 500)):
            _make_owned_post(s, channel_id, 1000 + i, base, v, forwards_24h=int(v * 0.1))

        # subscriber history: median-of-window 1000, current (most recent) 2000 -> scale x2
        s.add(ParticipantSnapshot(channel_id=channel_id, captured_at=base, count=1000))
        s.add(ParticipantSnapshot(channel_id=channel_id, captured_at=base + timedelta(days=1), count=1000))
        s.add(ParticipantSnapshot(channel_id=channel_id, captured_at=base + timedelta(days=2), count=2000))
        s.flush()

    with session_scope() as s:
        # derive the expected cell from the same hour_bucket/day_class helpers
        # under test, in IST (posted_at is stored/compared in IST, not UTC)
        features = {"hour_bucket": hour_bucket(base_ist.hour), "day_class": day_class(base_ist),
                    "post_type_cluster": None, "merchant_key": None}
        result = predict(s, channel_id, features)

    # no NormalizedPost/PostClassification rows exist for these posts, so cluster_id
    # and merchant_key are None on every gathered row -- matches the requested
    # (None, None) cell exactly at the top fallback level.
    assert result["fallback_level"] == "hour_day_cluster_merchant"
    assert result["n_samples"] == 5
    assert result["subscriber_scale"] == pytest.approx(2.0)
    assert result["views_24h"] == 600          # median(100..500)=300, x2 subscriber scale
    assert result["forwards_24h"] == 60        # 300*2 * median forward_rate 0.1
    # no 1h/6h snapshots were created -> honestly null, never fabricated
    assert result["views_1h"] is None
    assert result["views_6h"] is None


def test_predict_no_history_returns_nones():
    from src.db.models import Channel
    from src.db.session import session_scope
    from src.services.analytics.prediction import predict

    with session_scope() as s:
        ch = Channel(tg_channel_id=202, username="predempty", title="E")
        s.add(ch)
        s.flush()
        channel_id = ch.id

    with session_scope() as s:
        result = predict(s, channel_id, {"hour_bucket": "09-11", "day_class": "weekday",
                                         "post_type_cluster": None, "merchant_key": None})

    assert result["views_24h"] is None
    assert result["forwards_24h"] is None
    assert result["fallback_level"] == "no_data"
    assert result["n_samples"] == 0
