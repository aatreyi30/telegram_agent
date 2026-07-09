"""Integration coverage for the agentic daily/weekly planning wiring:
- daily_brief's headline `recommended_posts`/`cadence_why` now come from the AI's own
  plan, safety-clamped against the deterministic median/30d max.
- weekly_brief persists the AI digest onto the current week's CampaignPlan row and
  exposes per-day follower deltas alongside posts/views."""
from __future__ import annotations
import os, tempfile
from datetime import date, datetime, timedelta, timezone
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
    from src.db.models_campaign import CampaignPlan, PlanType
    from src.db.models_growth_snapshot import DailySubscriberStat

    init_db()
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C")
        s.add(ch)
        s.flush()

        # 60 days of steady 1-post/day owned activity ending 2026-06-30, so every
        # daily_brief target date used below (07-01..07-03) sees the same
        # deterministic median (1) and 30d max (1) regardless of small day shifts.
        base = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
        for i in range(60):
            p = Post(channel_id=ch.id, tg_message_id=i, posted_at=base - timedelta(days=i),
                     collected_at=base, views=50)
            s.add(p)
            s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                                 normalized_at=base, primary_merchant_key="amazon"))

        # 7 days of owned posts + a WEEKLY blueprint + subscriber stats for weekly_brief.
        # weekly_brief now resolves "end=2026-07-08" (a Wednesday) to the real IST
        # calendar week containing it: Mon 2026-07-06 -> Sun 2026-07-12.
        wk_base = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
        for i in range(7):
            p = Post(channel_id=ch.id, tg_message_id=1000 + i, posted_at=wk_base - timedelta(days=i),
                     collected_at=wk_base, views=80)
            s.add(p)
            s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                                 normalized_at=wk_base, primary_merchant_key="amazon"))

        s.add(CampaignPlan(
            plan_type=PlanType.WEEKLY, title="Week of 2026-07-06",
            target_date=date(2026, 7, 6), end_date=date(2026, 7, 12),
            blueprint={"daily_themes": {}}, confidence=0.5,
            generated_at=datetime.now(timezone.utc), is_ai_generated=False))

        s.add(DailySubscriberStat(
            channel_id=ch.id, stat_date=date(2026, 7, 6),
            subs_start=1000, subs_end=1010, subs_joined=10, subs_left=2, subs_net=8))
        s.add(DailySubscriberStat(
            channel_id=ch.id, stat_date=date(2026, 7, 9),
            subs_start=1010, subs_end=1010, subs_joined=5, subs_left=5, subs_net=0))
        s.flush()
    yield


def _plan(recommended_posts, cadence_why):
    return {
        "available": True,
        "digest": "AI daily digest.",
        "plan": {"recommended_posts": recommended_posts, "cadence_why": cadence_why,
                 "post_slots": [], "emphasis": None, "watch": None, "cited_numbers": []},
        "facts": [],
    }


def test_daily_brief_uses_ai_number_when_in_range(monkeypatch):
    from src.controllers import service

    monkeypatch.setattr(
        "src.ai.planner.generate_day_plan",
        lambda s, day=None, inputs=None: _plan(2, "AI says 2 is right"),
    )
    r = service.daily_brief(date="2026-07-01")
    assert r["today"]["recommended_posts"] == 2
    assert r["today"]["plan_clamped"] is False
    assert r["today"]["cadence_why"] == "AI says 2 is right"


def test_daily_brief_clamps_out_of_range_ai_number(monkeypatch):
    from src.controllers import service

    monkeypatch.setattr(
        "src.ai.planner.generate_day_plan",
        lambda s, day=None, inputs=None: _plan(10, "AI says 10, way too many"),
    )
    r = service.daily_brief(date="2026-07-02")
    assert r["today"]["recommended_posts"] == 3  # clipped to 3 * recent_max_30d (1)
    assert r["today"]["plan_clamped"] is True
    assert "active days ran" in r["today"]["cadence_why"]  # deterministic fallback text


def test_daily_brief_falls_back_to_deterministic_when_ai_unavailable(monkeypatch):
    from src.controllers import service

    monkeypatch.setattr(
        "src.ai.planner.generate_day_plan",
        lambda s, day=None, inputs=None: {"available": False},
    )
    r = service.daily_brief(date="2026-07-03")
    assert r["ai_available"] is False
    assert r["today"]["recommended_posts"] == 1  # deterministic median
    assert r["today"]["plan_clamped"] is False
    assert "active days ran" in r["today"]["cadence_why"]


def test_weekly_brief_adds_follower_deltas_and_persists_digest(monkeypatch):
    from sqlalchemy import select
    from src.controllers import service
    from src.db.session import session_scope
    from src.db.models_campaign import CampaignPlan, PlanType, CAMPAIGN_VERSION

    monkeypatch.setattr(
        "src.ai.briefing.BriefingGenerator.generate",
        lambda self, weekly=False: "Weekly digest text.",
    )

    r = service.weekly_brief(end="2026-07-08")
    assert r["ai_available"] is True
    assert r["digest"] == "Weekly digest text."

    assert r["week_start"] == "2026-07-06"
    assert r["week_end"] == "2026-07-12"

    by_date = {d["date"]: d for d in r["days"]}
    assert by_date["2026-07-06"]["joined"] == 10
    assert by_date["2026-07-06"]["left"] == 2
    assert by_date["2026-07-06"]["net"] == 8
    assert by_date["2026-07-09"]["net"] == 0
    # A day with no DailySubscriberStat row gap-fills to zero, not a KeyError/None.
    assert by_date["2026-07-07"] == {"date": "2026-07-07", "weekday": "Tue",
                                      "posts": by_date["2026-07-07"]["posts"],
                                      "views_avg": by_date["2026-07-07"]["views_avg"],
                                      "joined": 0, "left": 0, "net": 0}

    with session_scope() as s:
        wk = s.scalar(select(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.WEEKLY))
        assert wk.ai_digest == "Weekly digest text."
        assert wk.is_ai_generated is True


def test_weekly_brief_reuses_cached_digest_on_second_call(monkeypatch):
    """Regression test: weekly_brief() must call the AI at most once per calendar
    week. Before this fix, weekly_brief() had no create-path for a missing WEEKLY
    CampaignPlan row (unlike daily_brief()'s persist_ai_plan) — every single call
    fell through to a fresh, non-deterministic Groq call. This reproduces exactly
    the reported symptom: open the weekly plan twice, get two different digests."""
    from src.controllers import service

    calls = {"n": 0}

    def _fake_generate(self, weekly=False):
        calls["n"] += 1
        return f"Digest attempt #{calls['n']}"

    monkeypatch.setattr("src.ai.briefing.BriefingGenerator.generate", _fake_generate)

    # A week with no pre-existing CampaignPlan row or seeded data (the earlier test
    # in this module already cached 2026-07-06..07-12) — exercises the create-path
    # that was missing: weekly_brief() previously could only UPDATE an existing
    # row, never INSERT one, so it called the AI fresh on every single request.
    first = service.weekly_brief(end="2026-09-02")
    second = service.weekly_brief(end="2026-09-02")

    assert calls["n"] == 1, "AI must only be called once for the same calendar week"
    assert first["digest"] == "Digest attempt #1"
    assert second["digest"] == "Digest attempt #1"  # reused, not "attempt #2"

    # A different date INSIDE THE SAME calendar week must also hit the same cache.
    third = service.weekly_brief(end=first["week_start"])
    assert calls["n"] == 1
    assert third["digest"] == "Digest attempt #1"
    assert third["week_start"] == first["week_start"]
