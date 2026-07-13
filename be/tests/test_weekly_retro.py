"""Phase 2.4 tests -- RetroEngine: deterministic adjustment thresholds,
MAPE/bias math, plan adherence, and churn-vs-frequency. Mirrors the
test_prediction_baseline.py / test_outcome_collector.py style: pure-function
unit tests on small in-memory row dicts, plus a couple of DB-backed tests and
one end-to-end ``build_weekly_retro`` run."""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timedelta, timezone

import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/retro.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db

    init_db()
    yield


def _row(post_id=1, hb="09-11", merchant=None, type_label=None, engagement=None,
        forward_rate=None, views=None, err=None, pred=None):
    return {
        "post_id": post_id, "hour_bucket": hb, "day_class": "weekday",
        "merchant": merchant, "type_label": type_label,
        "engagement_score": engagement, "forward_rate": forward_rate,
        "views_24h": views, "err_views_24h": err, "predicted_views_24h": pred,
    }


# --------------------------------------------------------------------------- #
# _prediction_summary -- pure, no DB
# --------------------------------------------------------------------------- #
def test_prediction_summary_mape_and_bias():
    from src.services.analytics.retro import _prediction_summary

    rows = [_row(err=0.5), _row(err=-0.3), _row(err=0.1)]
    out = _prediction_summary(rows)
    assert out["n_posts"] == 3
    assert out["mape_views_24h"] == pytest.approx((0.5 + 0.3 + 0.1) / 3)
    assert out["bias"] == pytest.approx((0.5 - 0.3 + 0.1) / 3)


def test_prediction_summary_no_predictions_is_honestly_null():
    from src.services.analytics.retro import _prediction_summary

    out = _prediction_summary([_row(err=None), _row(err=None)])
    assert out == {"mape_views_24h": None, "n_posts": 0, "bias": None}


# --------------------------------------------------------------------------- #
# _top_misses -- pure, no DB
# --------------------------------------------------------------------------- #
def test_top_misses_over_and_under():
    from src.services.analytics.retro import _top_misses

    rows = [
        _row(post_id=1, pred=1200, views=4100, err=(4100 - 1200) / 1200, merchant="amazon"),
        _row(post_id=2, pred=3000, views=900, err=(900 - 3000) / 3000, merchant="flipkart"),
        _row(post_id=3, pred=1000, views=1000, err=0.0),
    ]
    over, under = _top_misses(rows, n=1)
    assert over[0]["post_id"] == 1 and over[0]["pred"] == 1200 and over[0]["actual"] == 4100
    assert under[0]["post_id"] == 2 and under[0]["pred"] == 3000 and under[0]["actual"] == 900


def test_top_misses_ignores_rows_without_a_prediction():
    from src.services.analytics.retro import _top_misses

    rows = [_row(post_id=1, err=None, pred=None, views=500)]
    over, under = _top_misses(rows)
    assert over == [] and under == []


# --------------------------------------------------------------------------- #
# _engagement_summary -- pure, no DB
# --------------------------------------------------------------------------- #
def test_engagement_summary_picks_best_bucket_and_type():
    from src.services.analytics.retro import _engagement_summary

    rows = [
        _row(hb="09-11", type_label="loot", engagement=0.2, forward_rate=0.01),
        _row(hb="21-23", type_label="coupon", engagement=0.9, forward_rate=0.03),
        _row(hb="21-23", type_label="coupon", engagement=0.8, forward_rate=0.02),
    ]
    out = _engagement_summary(rows)
    assert out["best_hour_bucket"] == "21-23"
    assert out["best_type_by_engagement"] == "coupon"
    assert out["median_forward_rate"] == pytest.approx(0.02)


def test_engagement_summary_empty_rows():
    from src.services.analytics.retro import _engagement_summary

    out = _engagement_summary([])
    assert out == {"median_forward_rate": None, "best_hour_bucket": None, "best_type_by_engagement": None}


# --------------------------------------------------------------------------- #
# _adjustments -- deterministic threshold rules, NOT AI
# --------------------------------------------------------------------------- #
def test_adjustments_shift_toward_high_engagement_bucket():
    from src.services.analytics.retro import _adjustments

    # bucket A: 5 posts, low engagement. bucket B: 5 posts, high engagement -> only B fires.
    rows = (
        [_row(hb="09-11", engagement=0.1) for _ in range(5)]
        + [_row(hb="21-23", engagement=0.9) for _ in range(5)]
    )
    adjustments = _adjustments(rows)
    assert any("shift toward 21-23" in a for a in adjustments)
    assert not any("shift toward 09-11" in a for a in adjustments)


def test_adjustments_reduce_low_engagement_merchant_and_type():
    from src.services.analytics.retro import _adjustments

    rows = (
        [_row(merchant="amazon", type_label="loot", engagement=0.9) for _ in range(5)]
        + [_row(merchant="nykaa", type_label="coupon", engagement=0.05) for _ in range(5)]
    )
    adjustments = _adjustments(rows)
    assert any("reduce merchant nykaa" in a for a in adjustments)
    assert any("reduce type coupon" in a for a in adjustments)
    assert not any("reduce merchant amazon" in a for a in adjustments)
    assert not any("reduce type loot" in a for a in adjustments)


def test_adjustments_requires_minimum_samples():
    from src.services.analytics.retro import _adjustments

    # only 3 posts per bucket -- below MIN_ADJUSTMENT_SAMPLES=5 -> no rule fires
    rows = (
        [_row(hb="09-11", engagement=0.1) for _ in range(3)]
        + [_row(hb="21-23", engagement=0.9) for _ in range(3)]
    )
    assert _adjustments(rows) == []


def test_adjustments_no_data_returns_empty():
    from src.services.analytics.retro import _adjustments

    assert _adjustments([]) == []


# --------------------------------------------------------------------------- #
# _plan_adherence -- DB-backed (ScheduledPost)
# --------------------------------------------------------------------------- #
def _scheduled(s, scheduled_at, status, key, last_error=None):
    from src.db.models_automation import ScheduledPost

    row = ScheduledPost(channel_ref="testchan", scheduled_at=scheduled_at, status=status,
                       last_error=last_error, idempotency_key=key)
    s.add(row)
    return row


def test_plan_adherence_counts_published_blocked_stale_and_skipped():
    from src.db.models_automation import ScheduleStatus
    from src.db.session import session_scope
    from src.services.analytics.retro import _plan_adherence

    week_start = date(2026, 6, 1)  # a Monday
    week_end = week_start + timedelta(days=6)
    mid = datetime(2026, 6, 3, 10, 0, tzinfo=timezone.utc)

    with session_scope() as s:
        for i in range(3):
            _scheduled(s, mid + timedelta(hours=i), ScheduleStatus.PUBLISHED, key=f"pa-pub{i}")
        _scheduled(s, mid, ScheduleStatus.BLOCKED, key="pa-bs1", last_error="blocked_stale: dead link (404)")
        _scheduled(s, mid, ScheduleStatus.FAILED, key="pa-fail1")
        s.flush()

    with session_scope() as s:
        out = _plan_adherence(s, week_start, week_end)

    assert out == {"planned": 5, "published": 3, "blocked_stale": 1, "skipped": 1}


def test_plan_adherence_excludes_rows_outside_the_week():
    from src.db.models_automation import ScheduleStatus
    from src.db.session import session_scope
    from src.services.analytics.retro import _plan_adherence

    week_start = date(2026, 6, 8)
    week_end = week_start + timedelta(days=6)
    outside = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)  # a week before

    with session_scope() as s:
        _scheduled(s, outside, ScheduleStatus.PUBLISHED, key="pa-outside1")
        s.flush()

    with session_scope() as s:
        out = _plan_adherence(s, week_start, week_end)

    assert out["planned"] == 0


# --------------------------------------------------------------------------- #
# _churn_vs_frequency -- DB-backed (DailySubscriberStat + Post)
# --------------------------------------------------------------------------- #
def test_churn_vs_frequency_high_vs_low_churn_days():
    from src.db.models import Channel, Post
    from src.db.models_growth_snapshot import DailySubscriberStat
    from src.db.session import session_scope
    from src.services.analytics.retro import _churn_vs_frequency

    with session_scope() as s:
        ch = Channel(tg_channel_id=401, username="churnch", title="C")
        s.add(ch)
        s.flush()
        channel_id = ch.id

        week_end = date(2026, 6, 28)
        # 14 days: first 7 = high churn (subs_left=50, 20 posts/day),
        # last 7 = low churn (subs_left=5, 5 posts/day).
        for i in range(14):
            d = week_end - timedelta(days=13 - i)
            leave = 50 if i < 7 else 5
            s.add(DailySubscriberStat(channel_id=channel_id, stat_date=d, subs_start=1000,
                                      subs_end=1000 - leave, subs_joined=0, subs_left=leave,
                                      subs_net=-leave))
            n_posts = 20 if i < 7 else 5
            base = datetime(d.year, d.month, d.day, 12, 0, tzinfo=timezone.utc)
            for j in range(n_posts):
                s.add(Post(channel_id=channel_id, tg_message_id=1000 * i + j,
                           posted_at=base + timedelta(minutes=j), collected_at=base))
        s.flush()

    with session_scope() as s:
        out = _churn_vs_frequency(s, channel_id, week_end)

    assert out["high_leave_days_posts_per_day"] == pytest.approx(20.0)
    assert out["low_leave_days_posts_per_day"] == pytest.approx(5.0)


def test_churn_vs_frequency_no_channel_is_null():
    from src.db.session import session_scope
    from src.services.analytics.retro import _churn_vs_frequency

    with session_scope() as s:
        out = _churn_vs_frequency(s, None, date(2026, 6, 28))
    assert out == {"high_leave_days_posts_per_day": None, "low_leave_days_posts_per_day": None}


# --------------------------------------------------------------------------- #
# build_weekly_retro -- end-to-end, idempotent per week
# --------------------------------------------------------------------------- #
def test_build_weekly_retro_end_to_end_and_idempotent():
    from sqlalchemy import func, select

    from src.db.models import Channel, Post
    from src.db.models_ai_output import AIOutput
    from src.db.models_automation import ScheduledPost, ScheduleStatus
    from src.db.models_growth_snapshot import DailySubscriberStat
    from src.db.models_prediction import PostOutcome, PostPrediction, WeeklyRetro
    from src.db.session import session_scope
    from src.services.analytics.retro import build_weekly_retro

    anchor = date(2026, 5, 20)
    week_start = anchor - timedelta(days=anchor.weekday())
    week_end = week_start + timedelta(days=6)

    with session_scope() as s:
        # participants_count set explicitly (and higher than any other test's
        # channel in this module-scoped shared DB) so `_owned_channel`'s
        # `ORDER BY participants_count DESC` deterministically resolves to
        # *this* channel -- NULLs (the default, e.g. test_churn_vs_frequency's
        # channel 401) sort last in SQLite's DESC order, but two NULLs tie in
        # an unspecified order, which previously let an earlier test's channel
        # win by accident.
        ch = Channel(tg_channel_id=501, username="retrowk", title="R", participants_count=999_999)
        s.add(ch)
        s.flush()
        channel_id = ch.id

        posted_at = datetime(week_start.year, week_start.month, week_start.day, 10, 0,
                             tzinfo=timezone.utc) + timedelta(days=1)
        p1 = Post(channel_id=channel_id, tg_message_id=1, posted_at=posted_at, collected_at=posted_at)
        s.add(p1)
        s.flush()
        p1_id = p1.id
        s.add(PostOutcome(post_id=p1_id, views_24h=4100, forwards_24h=40, reactions_24h=10,
                          forward_rate=0.0098, reaction_rate=0.0024, engagement_score=0.8,
                          err_views_24h=(4100 - 1200) / 1200,
                          phase_1h_done=True, phase_6h_done=True, phase_24h_done=True))
        s.add(PostPrediction(post_id=p1_id, predicted_views_24h=1200, model_version="baseline_v1", features={}))

        posted_at2 = posted_at + timedelta(hours=3)
        p2 = Post(channel_id=channel_id, tg_message_id=2, posted_at=posted_at2, collected_at=posted_at2)
        s.add(p2)
        s.flush()
        p2_id = p2.id
        s.add(PostOutcome(post_id=p2_id, views_24h=900, forwards_24h=5, reactions_24h=1,
                          forward_rate=0.0055, reaction_rate=0.0011, engagement_score=0.2,
                          err_views_24h=(900 - 3000) / 3000,
                          phase_1h_done=True, phase_6h_done=True, phase_24h_done=True))
        s.add(PostPrediction(post_id=p2_id, predicted_views_24h=3000, model_version="baseline_v1", features={}))

        s.add(ScheduledPost(channel_ref="retrowk", scheduled_at=posted_at, status=ScheduleStatus.PUBLISHED,
                            idempotency_key="wk-pub-1"))
        s.add(ScheduledPost(channel_ref="retrowk", scheduled_at=posted_at2, status=ScheduleStatus.BLOCKED,
                            last_error="blocked_stale: dead link (404)", idempotency_key="wk-bs-1"))

        for i in range(14):
            d = week_end - timedelta(days=13 - i)
            s.add(DailySubscriberStat(channel_id=channel_id, stat_date=d, subs_start=1000, subs_end=990,
                                      subs_joined=0, subs_left=10, subs_net=-10))
        s.flush()

    with session_scope() as s:
        row = build_weekly_retro(s, week_start)
        metrics = row.metrics
        narrative = row.narrative

    assert metrics["prediction"]["n_posts"] == 2
    expected_mape = (abs((4100 - 1200) / 1200) + abs((900 - 3000) / 3000)) / 2
    assert metrics["prediction"]["mape_views_24h"] == pytest.approx(expected_mape, abs=1e-3)
    assert metrics["plan_adherence"] == {"planned": 2, "published": 1, "blocked_stale": 1, "skipped": 0}
    assert {r["post_id"] for r in metrics["top_over"] + metrics["top_under"]} == {p1_id, p2_id}
    assert metrics["top_over"][0]["post_id"] == p1_id   # biggest over-performer
    assert metrics["top_under"][0]["post_id"] == p2_id  # biggest under-performer
    # only 1 post per hour bucket this week -> below MIN_ADJUSTMENT_SAMPLES, no merchant/type
    # data linked (no NormalizedPost rows) -> no adjustment can be trusted yet.
    assert metrics["adjustments"] == []
    assert set(metrics["churn_vs_frequency"].keys()) == {
        "high_leave_days_posts_per_day", "low_leave_days_posts_per_day"
    }
    assert isinstance(narrative, str) and narrative  # AI unavailable in tests -> deterministic fallback, never empty

    with session_scope() as s:
        n_outputs = s.scalar(
            select(func.count()).select_from(AIOutput).where(AIOutput.kind == "retro_narrative")
        )
        n_retros = s.scalar(
            select(func.count()).select_from(WeeklyRetro).where(WeeklyRetro.week_start == week_start)
        )
    assert n_outputs >= 1
    assert n_retros == 1

    # rerun for the SAME week -- must update in place, not duplicate (uq_weekly_retro_week)
    with session_scope() as s:
        build_weekly_retro(s, week_start)
        n_retros_again = s.scalar(
            select(func.count()).select_from(WeeklyRetro).where(WeeklyRetro.week_start == week_start)
        )
    assert n_retros_again == 1


def test_build_weekly_retro_no_data_does_not_crash():
    from src.services.analytics.retro import build_weekly_retro
    from src.db.session import session_scope

    anchor = date(2026, 3, 2)
    week_start = anchor - timedelta(days=anchor.weekday())
    with session_scope() as s:
        row = build_weekly_retro(s, week_start)
    assert row.metrics["prediction"] == {"mape_views_24h": None, "n_posts": 0, "bias": None}
    assert row.metrics["adjustments"] == []
    assert row.metrics["top_over"] == [] and row.metrics["top_under"] == []


# --------------------------------------------------------------------------- #
# Wiring: ai/context.latest_retro + ai/planner.build_plan_context
# --------------------------------------------------------------------------- #
def test_context_latest_retro_absent_then_present():
    from sqlalchemy import func, select

    from src.ai.context import latest_retro
    from src.db.models_prediction import WeeklyRetro
    from src.db.session import session_scope
    from src.services.analytics.retro import build_weekly_retro

    # This module-scoped DB is shared with earlier tests in this file that
    # already build a WeeklyRetro row or two, so we can't assert global
    # absence here. Instead: pick a week later than every other week_start
    # used in this module (`latest_retro`'s `ORDER BY week_start DESC` is then
    # guaranteed to surface it) and confirm the row count increases by
    # exactly one -- an order-independent "was absent, now present" check.
    anchor = date(2026, 12, 7)
    week_start = anchor - timedelta(days=anchor.weekday())

    with session_scope() as s:
        n_before = s.scalar(select(func.count()).select_from(WeeklyRetro))

    with session_scope() as s:
        build_weekly_retro(s, week_start)

    with session_scope() as s:
        n_after = s.scalar(select(func.count()).select_from(WeeklyRetro))
        got = latest_retro(s)

    assert n_after == n_before + 1
    assert got is not None
    assert got["week_start"] == week_start.isoformat()
    assert "adjustments" in got["metrics"]


def test_build_plan_context_includes_retro_key():
    from src.ai.planner import build_plan_context
    from src.db.session import session_scope

    with session_scope() as s:
        ctx = build_plan_context(s, date(2026, 4, 10))
    assert "retro" in ctx
