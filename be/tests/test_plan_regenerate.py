"""Steer & Regenerate for the Plan tab:
- an elapsed (already-past) day/week refuses to regenerate with a clear reason;
- regenerating today replaces the cached CampaignPlan row and stores the operator
  directive on the fresh row (no duplicate rows left behind);
- the directive reaches the planner's prompt-building path as a highest-priority
  block, without bypassing the fact-check (still built from `build_plan_context`
  the same way `generate_day_plan` always has)."""
from __future__ import annotations
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db, session_scope
    from src.db.models import Channel, Post
    from src.db.models_normalization import NormalizedPost, SourceType
    from src.services.analytics.periods import ist_today

    init_db()
    today = ist_today()
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C")
        s.add(ch)
        s.flush()
        # 20 days of owned posts ending TODAY (IST) so daily_brief's deterministic
        # inputs (trajectory, cadence, etc.) have real activity behind them for
        # both "today" and "an elapsed day".
        base = datetime(today.year, today.month, today.day, 12, 0, tzinfo=timezone.utc)
        for i in range(20):
            p = Post(channel_id=ch.id, tg_message_id=i, posted_at=base - timedelta(days=i),
                     collected_at=base, views=100 + i)
            s.add(p)
            s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                                 normalized_at=base, primary_merchant_key="amazon"))
    yield


def _fake_ai_result(day, digest="Fake steered digest."):
    return {
        "available": True,
        "digest": digest,
        "plan": {"date": day, "recommended_posts": 5, "cadence_why": "test",
                 "post_slots": [{"type": "single", "window_ist": "12:00-13:00",
                                  "count": 5, "theme": "electronics", "merchant": "amazon",
                                  "why": "x"}],
                 "emphasis": "push electronics", "watch": "forwards", "cited_numbers": []},
        "facts": [],
    }


# --- elapsed-day / elapsed-week guard -----------------------------------------

def test_regenerate_daily_refuses_an_elapsed_day():
    from src.controllers import service

    r = service.regenerate_daily(date="2020-01-06")
    assert r["available"] is False
    assert r["reason"] == "This day has already elapsed — regenerating it has no effect."


def test_regenerate_weekly_refuses_an_elapsed_week():
    from src.controllers import service

    r = service.regenerate_weekly(end="2020-01-06")
    assert r["available"] is False
    assert r["reason"] == "This day has already elapsed — regenerating it has no effect."


# --- regenerate today replaces the cached row + stores the directive ----------

def test_regenerate_daily_replaces_cached_row_and_stores_directive(monkeypatch):
    from sqlalchemy import select
    from src.controllers import service
    from src.db.session import session_scope
    from src.db.models_campaign import CampaignPlan, PlanType, CAMPAIGN_VERSION
    from src.services.analytics.periods import ist_today

    today = ist_today()
    today_str = today.isoformat()

    calls = []

    def fake_generate_day_plan(s, day=None, inputs=None, directive=None):
        calls.append(directive)
        return _fake_ai_result(day.isoformat(), digest=f"digest #{len(calls)}")

    monkeypatch.setattr("src.ai.planner.generate_day_plan", fake_generate_day_plan)

    # First, a normal (non-regenerate) request populates the cache, as it always does.
    first = service.daily_brief(date=today_str)
    assert first["available"] is True
    assert first["operator_directive"] is None
    assert first["can_regenerate"] is True
    assert len(calls) == 1
    assert calls[0] is None  # normal path never threads a directive

    with session_scope() as s:
        rows = s.scalars(select(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.DAILY,
            CampaignPlan.target_date == today)).all()
        assert len(rows) == 1

    # Now steer & regenerate — must call the AI again (fresh miss), store the
    # directive, and leave exactly ONE row behind (the stale one was deleted).
    directive = "Push electronics hard today, avoid repeating the same merchant."
    second = service.regenerate_daily(date=today_str, directive=directive)
    assert second["available"] is True
    assert second["operator_directive"] == directive
    assert len(calls) == 2
    assert calls[1] == directive  # the directive reached generate_day_plan

    with session_scope() as s:
        rows = s.scalars(select(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.DAILY,
            CampaignPlan.target_date == today)).all()
        assert len(rows) == 1, "regenerate must not leave duplicate cached rows behind"
        assert rows[0].operator_directive == directive
        assert rows[0].ai_digest == "digest #2"

    # Reopening the plan afterwards must surface the persisted directive so the
    # FE can prefill the steering box.
    third = service.daily_brief(date=today_str)
    assert third["operator_directive"] == directive
    assert len(calls) == 2, "reopening must reuse the cached row, not regenerate again"


def test_regenerate_weekly_replaces_cached_row_and_stores_directive(monkeypatch):
    from sqlalchemy import select
    from src.controllers import service
    from src.db.session import session_scope
    from src.db.models_campaign import CampaignPlan, PlanType, CAMPAIGN_VERSION
    from src.services.analytics.periods import ist_today
    from datetime import timedelta

    today = ist_today()
    week_start = today - timedelta(days=today.weekday())

    calls = []

    def fake_generate(s, week_start=None, directive=None):
        calls.append(directive)
        return {"available": True, "digest": f"weekly digest #{len(calls)}"}

    monkeypatch.setattr("src.ai.planner.generate_week_plan", fake_generate)

    first = service.weekly_brief(end=week_start.isoformat())
    assert first["available"] is True
    assert first["operator_directive"] is None
    assert first["can_regenerate"] is True
    assert len(calls) == 1
    assert calls[0] is None

    directive = "Lean into the festival theme this week."
    second = service.regenerate_weekly(end=week_start.isoformat(), directive=directive)
    assert second["available"] is True
    assert second["operator_directive"] == directive
    assert len(calls) == 2
    assert calls[1] == directive

    with session_scope() as s:
        rows = s.scalars(select(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.WEEKLY,
            CampaignPlan.target_date == week_start)).all()
        assert len(rows) == 1, "regenerate must not leave duplicate cached rows behind"
        assert rows[0].operator_directive == directive


# --- directive reaches the planner's prompt-building path ---------------------

def test_build_plan_context_surfaces_operator_directive():
    from datetime import date
    from src.ai.planner import build_plan_context
    from src.db.session import session_scope

    with session_scope() as s:
        ctx = build_plan_context(s, date(2026, 8, 3), directive="Focus on electronics.")
    assert ctx["operator_directive"] == "Focus on electronics."


def test_build_plan_context_operator_directive_defaults_none():
    from datetime import date
    from src.ai.planner import build_plan_context
    from src.db.session import session_scope

    with session_scope() as s:
        ctx = build_plan_context(s, date(2026, 8, 4))
    assert ctx["operator_directive"] is None


def test_generate_day_plan_injects_operator_directive_into_prompt(monkeypatch):
    """Mirrors the existing planner tests' style (test_ai_planner.py): stub the
    AI client and assert on the exact prompt text built for it, rather than
    hitting a real model."""
    from datetime import date
    from src.db.session import session_scope
    import src.ai.planner as planner_mod

    captured = {}

    class _FakeAIClient:
        def complete(self, user, *, system_extra="", max_tokens=2400, effort="medium",
                     trace_call=None, channel_id=None):
            captured["user"] = user
            return (
                "Fake digest.\n===PLAN===\n"
                '{"date":"2026-08-05","recommended_posts":3,"cadence_why":"x",'
                '"post_slots":[],"emphasis":"e","watch":"w","cited_numbers":[]}'
            )

    monkeypatch.setattr(planner_mod, "AIClient", lambda: _FakeAIClient())

    with session_scope() as s:
        result = planner_mod.generate_day_plan(
            s, date(2026, 8, 5), inputs={"recommended_posts": 3},
            directive="Push electronics harder today.")

    assert result["available"] is True
    user = captured["user"]
    assert "OPERATOR DIRECTIVE" in user
    assert "Push electronics harder today." in user
    # highest-priority framing (honor-or-explain) + the merchant-availability guard
    assert "honor it, or state PLAINLY in the narrative why it can't be honored" in user
    assert "ONLY merchants with deals in" in user


def test_generate_day_plan_omits_operator_directive_block_when_absent(monkeypatch):
    from datetime import date
    from src.db.session import session_scope
    import src.ai.planner as planner_mod

    captured = {}

    class _FakeAIClient:
        def complete(self, user, *, system_extra="", max_tokens=2400, effort="medium",
                     trace_call=None, channel_id=None):
            captured["user"] = user
            return (
                "Fake digest.\n===PLAN===\n"
                '{"date":"2026-08-06","recommended_posts":3,"cadence_why":"x",'
                '"post_slots":[],"emphasis":"e","watch":"w","cited_numbers":[]}'
            )

    monkeypatch.setattr(planner_mod, "AIClient", lambda: _FakeAIClient())

    with session_scope() as s:
        result = planner_mod.generate_day_plan(s, date(2026, 8, 6), inputs={"recommended_posts": 3})

    assert result["available"] is True
    assert "OPERATOR DIRECTIVE" not in captured["user"]
