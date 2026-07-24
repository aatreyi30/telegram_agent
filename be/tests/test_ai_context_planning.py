"""Unit tests for the three planning-support additions to `src/ai/context.py`:
clamp_recommended_posts (pure), prev_week_digest, follower_deltas_by_day."""
from __future__ import annotations
import os, tempfile
from datetime import date, datetime, timezone
import pytest

_state: dict = {}


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db, session_scope
    from src.db.models import Channel
    from src.db.models_campaign import CampaignPlan, PlanType
    from src.db.models_growth_snapshot import DailySubscriberStat

    init_db()
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C")
        s.add(ch)
        s.flush()

        # Previous week's WEEKLY plan, ending right before the current week starts.
        s.add(CampaignPlan(
            plan_type=PlanType.WEEKLY, title="Week of 2026-06-29",
            target_date=date(2026, 6, 29), end_date=date(2026, 7, 5),
            blueprint={"daily_themes": {}}, confidence=0.5,
            generated_at=datetime.now(timezone.utc),
            is_ai_generated=True, ai_digest="Last week: steady cadence, views flat."))

        # A non-AI-generated WEEKLY plan for a different prior week — must not surface.
        s.add(CampaignPlan(
            plan_type=PlanType.WEEKLY, title="Week of 2026-06-22",
            target_date=date(2026, 6, 22), end_date=date(2026, 6, 28),
            blueprint={}, confidence=0.5, generated_at=datetime.now(timezone.utc),
            is_ai_generated=False))

        s.add(DailySubscriberStat(
            channel_id=ch.id, stat_date=date(2026, 7, 6),
            subs_start=1000, subs_end=1010, subs_joined=15, subs_left=5, subs_net=10))
        s.add(DailySubscriberStat(
            channel_id=ch.id, stat_date=date(2026, 7, 8),
            subs_start=1010, subs_end=1005, subs_joined=3, subs_left=8, subs_net=-5))
        s.flush()
        _state["channel_id"] = ch.id
    yield


# --- clamp_recommended_posts -------------------------------------------------

def test_clamp_in_range_passthrough():
    from src.ai.context import clamp_recommended_posts
    value, clamped = clamp_recommended_posts(6, recent_median=5, recent_max_30d=10)
    assert value == 6
    assert clamped is False


def test_clamp_over_ceiling_clips():
    from src.ai.context import clamp_recommended_posts
    value, clamped = clamp_recommended_posts(100, recent_median=5, recent_max_30d=10)
    assert value == 30  # 3 * recent_max_30d
    assert clamped is True


def test_clamp_zero_while_active_floors_to_one():
    from src.ai.context import clamp_recommended_posts
    value, clamped = clamp_recommended_posts(0, recent_median=5, recent_max_30d=10)
    assert value == 1
    assert clamped is True


def test_clamp_zero_median_allows_zero_no_clamp():
    from src.ai.context import clamp_recommended_posts
    value, clamped = clamp_recommended_posts(0, recent_median=0, recent_max_30d=0)
    assert value == 0
    assert clamped is False


def test_clamp_no_max_30d_falls_back_to_median_ceiling():
    from src.ai.context import clamp_recommended_posts
    # ceiling = max(3*median, 5) = max(15, 5) = 15
    value, clamped = clamp_recommended_posts(20, recent_median=5, recent_max_30d=0)
    assert value == 15
    assert clamped is True


def test_clamp_none_candidate_is_availability_fallback_not_clamp():
    from src.ai.context import clamp_recommended_posts
    value, clamped = clamp_recommended_posts(None, recent_median=7, recent_max_30d=10)
    assert value == 7
    assert clamped is False


def test_clamp_unparseable_candidate_falls_back():
    from src.ai.context import clamp_recommended_posts
    value, clamped = clamp_recommended_posts("not-a-number", recent_median=4, recent_max_30d=None)
    assert value == 4
    assert clamped is False


# --- prev_week_digest ---------------------------------------------------------

def test_prev_week_digest_present():
    from src.ai.context import prev_week_digest
    from src.db.session import session_scope
    with session_scope() as s:
        digest = prev_week_digest(s, date(2026, 7, 6))
        assert digest == "Last week: steady cadence, views flat."


def test_prev_week_digest_absent_returns_none():
    from src.ai.context import prev_week_digest
    from src.db.session import session_scope
    with session_scope() as s:
        # No WEEKLY plan ends 2026-07-14 (i.e. week_start 2026-07-15 has no predecessor row).
        assert prev_week_digest(s, date(2026, 7, 15)) is None


def test_prev_week_digest_ignores_non_ai_generated_row():
    from src.ai.context import prev_week_digest
    from src.db.session import session_scope
    with session_scope() as s:
        # week_start 2026-06-29 -> prev_end 2026-06-28, which is the non-AI row.
        assert prev_week_digest(s, date(2026, 6, 29)) is None


# --- follower_deltas_by_day ---------------------------------------------------

def test_follower_deltas_rows_present():
    from src.ai.context import follower_deltas_by_day
    from src.db.session import session_scope
    with session_scope() as s:
        deltas = follower_deltas_by_day(s, _state["channel_id"], date(2026, 7, 6), date(2026, 7, 8))
        assert deltas["2026-07-06"] == {"joined": 15, "left": 5, "net": 10}
        assert deltas["2026-07-08"] == {"joined": 3, "left": 8, "net": -5}


def test_follower_deltas_gap_day_absent():
    from src.ai.context import follower_deltas_by_day
    from src.db.session import session_scope
    with session_scope() as s:
        deltas = follower_deltas_by_day(s, _state["channel_id"], date(2026, 7, 6), date(2026, 7, 8))
        assert "2026-07-07" not in deltas


def test_follower_deltas_empty_range_returns_empty_dict():
    from src.ai.context import follower_deltas_by_day
    from src.db.session import session_scope
    with session_scope() as s:
        deltas = follower_deltas_by_day(s, _state["channel_id"], date(2026, 8, 1), date(2026, 8, 7))
        assert deltas == {}


def test_follower_deltas_none_channel_id_returns_empty_dict():
    from src.ai.context import follower_deltas_by_day
    from src.db.session import session_scope
    with session_scope() as s:
        deltas = follower_deltas_by_day(s, None, date(2026, 7, 6), date(2026, 7, 8))
        assert deltas == {}
