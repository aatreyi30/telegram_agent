from __future__ import annotations
import os
import tempfile
from datetime import date, datetime, timezone

import pytest

from src.ai.planner import parse_plan


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db
    init_db()
    yield


def test_parse_plan_extracts_json_block():
    raw = (
        "Here is the plan:\n"
        '{"date":"2026-07-08","post_slots":[{"type":"single","window_ist":"12:00-13:00","theme":"electronics","why":"x"}],'
        '"emphasis":"push electronics","watch":"forwards down","cited_numbers":[2100,980,0.3]}\n'
        "Hope this helps!"
    )
    plan = parse_plan(raw)
    assert plan["date"] == "2026-07-08"
    assert plan["post_slots"][0]["theme"] == "electronics"
    assert plan["cited_numbers"] == [2100, 980, 0.3]


def test_parse_plan_raises_on_garbage():
    with pytest.raises(ValueError):
        parse_plan("no json here at all")


DAY = date(2026, 7, 8)
PREV = date(2026, 7, 7)


def test_build_plan_context_day_of_week():
    from src.ai.planner import build_plan_context
    from src.db.session import session_scope

    with session_scope() as s:
        ctx = build_plan_context(s, DAY)
    assert ctx["day_of_week"] == DAY.strftime("%A")


def test_build_plan_context_yesterday_digest_present():
    from src.db.models_campaign import CampaignPlan, PlanType
    from src.db.session import session_scope
    from src.ai.planner import build_plan_context

    with session_scope() as s:
        s.add(CampaignPlan(
            plan_type=PlanType.DAILY, title="AI day plan", target_date=PREV,
            blueprint={"post_slots": []}, confidence=0.6,
            generated_at=datetime.now(timezone.utc),
            is_ai_generated=True, ai_digest="Yesterday views up 12%."))

    with session_scope() as s:
        ctx = build_plan_context(s, DAY)
    assert ctx["yesterday_digest"] == "Yesterday views up 12%."


def test_build_plan_context_yesterday_digest_absent():
    from src.db.session import session_scope
    from src.ai.planner import build_plan_context

    other_day = date(2026, 8, 1)
    with session_scope() as s:
        ctx = build_plan_context(s, other_day)
    assert ctx["yesterday_digest"] is None


def test_build_plan_context_this_week_theme_present():
    from src.db.models_campaign import CampaignPlan, PlanType
    from src.db.session import session_scope
    from src.ai.planner import build_plan_context

    with session_scope() as s:
        s.add(CampaignPlan(
            plan_type=PlanType.WEEKLY, title="Weekly plan", target_date=PREV,
            end_date=PREV, blueprint={"daily_themes": [
                {"day": "Wed", "date": DAY.isoformat(), "theme_focus": "electronics",
                 "posts_planned": 8},
            ]}, confidence=0.6, generated_at=datetime.now(timezone.utc)))

    with session_scope() as s:
        ctx = build_plan_context(s, DAY)
    assert ctx["this_week_theme"] is not None
    assert ctx["this_week_theme"]["theme_focus"] == "electronics"


def test_build_plan_context_this_week_theme_absent():
    from src.db.session import session_scope
    from src.ai.planner import build_plan_context

    other_day = date(2026, 8, 2)
    with session_scope() as s:
        ctx = build_plan_context(s, other_day)
    assert ctx["this_week_theme"] is None


def test_factcheck_pool_includes_grounded_inputs(monkeypatch):
    """Regression: numbers the AI is shown in merchant_mix / posting_windows /
    deal_type_allocation must be in the factcheck pool, else a legitimately-cited
    'amazon share 0.316, 48.5 views/day' is flagged as a hallucination and the plan
    is marked untrusted (jit_fill then refuses it). Before the fix res['facts']
    omitted these structures and this plan failed factcheck."""
    from src.ai import planner
    from src.ai.factcheck import check_cited_numbers
    from src.db.session import session_scope

    canned = (
        "Digest.\n===PLAN===\n"
        '{"date":"2026-07-08","recommended_posts":4,'
        '"post_slots":[{"type":"single","window_ist":"18:00-20:00","theme":"electronics",'
        '"merchant":"amazon","why":"amazon share 0.316, 48.5 views/day, evening avg 20.2"}],'
        '"emphasis":"x","watch":"y","cited_numbers":[0.316,48.5,20.2]}'
    )
    monkeypatch.setattr(planner.AIClient, "complete", lambda self, *a, **k: canned)

    inputs = {
        "recommended_posts": 4,
        "posting_windows": [{"part": "Evening", "avg_views_per_day": 20.2}],
        "deal_type_allocation": [{"post_type": "single_deal", "target_posts": 3}],
        "merchant_allocation": [{"merchant_key": "amazon", "share": 0.316,
                                 "avg_views_per_day": 48.5}],
    }
    with session_scope() as s:
        res = planner.generate_day_plan(s, day=DAY, inputs=inputs)

    assert res["available"]
    fc = check_cited_numbers(res["plan"]["cited_numbers"], res["facts"])
    assert fc["status"] == "passed", fc["unverified"]
