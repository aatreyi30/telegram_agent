"""daily_brief() must cache its AI-generated portion per (day, campaign version) in
CampaignPlan, so repeat requests for the SAME day don't re-call the AI, while a
request for a different day still generates fresh."""
from __future__ import annotations
import os, tempfile
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

    init_db()
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C")
        s.add(ch)
        s.flush()
        # 20 days of owned posts ending 2026-06-20 (IST), so both 2026-06-20 and
        # 2026-06-19 have real activity behind them for the planner's inputs.
        base = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
        for i in range(20):
            p = Post(channel_id=ch.id, tg_message_id=i, posted_at=base - timedelta(days=i),
                     collected_at=base, views=100 + i)
            s.add(p)
            s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                                 normalized_at=base, primary_merchant_key="amazon"))
    yield


def _fake_ai_result(day):
    return {
        "available": True,
        "digest": f"Fake digest for {day}.",
        "plan": {"date": day, "recommended_posts": 5, "cadence_why": "test",
                 "post_slots": [{"type": "single", "window_ist": "12:00-13:00",
                                  "count": 5, "theme": "electronics", "merchant": "amazon",
                                  "why": "x"}],
                 "emphasis": "push electronics", "watch": "forwards", "cited_numbers": []},
        "facts": [],
    }


def test_daily_brief_caches_ai_call_per_day(monkeypatch):
    from src.controllers import service

    calls = []

    def fake_generate_day_plan(s, day=None, inputs=None):
        calls.append(day)
        return _fake_ai_result(day.isoformat())

    monkeypatch.setattr("src.ai.planner.generate_day_plan", fake_generate_day_plan)

    r1 = service.daily_brief(date="2026-06-20")
    assert r1["available"] is True
    assert r1["ai_available"] is True
    assert r1["digest"] == "Fake digest for 2026-06-20."
    assert len(calls) == 1

    # Repeat request for the SAME day must be served from the cached CampaignPlan
    # row — no second AI call.
    r2 = service.daily_brief(date="2026-06-20")
    assert r2["available"] is True
    assert r2["ai_available"] is True
    assert r2["digest"] == "Fake digest for 2026-06-20."
    assert r2["today"]["slots"] == r1["today"]["slots"]
    assert len(calls) == 1, "second same-day request should not re-call the AI"

    # A different day must still generate fresh (not reuse the other day's cache).
    r3 = service.daily_brief(date="2026-06-19")
    assert r3["available"] is True
    assert r3["digest"] == "Fake digest for 2026-06-19."
    assert len(calls) == 2

    # And a second request for THAT day is cached too.
    r4 = service.daily_brief(date="2026-06-19")
    assert r4["digest"] == "Fake digest for 2026-06-19."
    assert len(calls) == 2


def test_daily_brief_persists_a_campaign_plan_row():
    from sqlalchemy import select
    from src.db.session import session_scope
    from src.db.models_campaign import CampaignPlan, PlanType, CAMPAIGN_VERSION
    from datetime import date

    with session_scope() as s:
        rows = s.scalars(
            select(CampaignPlan)
            .where(CampaignPlan.plan_type == PlanType.DAILY,
                   CampaignPlan.campaign_version == CAMPAIGN_VERSION,
                   CampaignPlan.target_date == date(2026, 6, 20))
        ).all()
        assert len(rows) == 1
        assert rows[0].is_ai_generated is True
        assert rows[0].ai_digest == "Fake digest for 2026-06-20."
