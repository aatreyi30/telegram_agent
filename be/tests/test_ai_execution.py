from __future__ import annotations
import os, tempfile
from datetime import date, datetime, timezone
import pytest


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


def test_persist_ai_plan_writes_flagged_row():
    from src.services.generation.ai_execution import persist_ai_plan
    from src.db.models_campaign import CampaignPlan
    from src.db.session import session_scope
    from sqlalchemy import select
    result = {
        "available": True,
        "digest": "Views up 12% vs baseline.",
        "plan": {"date": "2026-07-08", "post_slots": [{"type": "single", "window_ist": "12:00-13:00", "theme": "electronics", "why": "x"}],
                 "emphasis": "push electronics", "watch": "forwards", "cited_numbers": [2100]},
        "report_ids": [1],
        "factcheck": {"status": "passed", "unverified": []},
    }
    with session_scope() as s:
        plan = persist_ai_plan(s, result)
        assert plan is not None
    with session_scope() as s:
        p = s.scalars(select(CampaignPlan)).one()
        assert p.is_ai_generated is True
        assert p.factcheck_status == "passed"
        assert p.blueprint["post_slots"][0]["theme"] == "electronics"
        assert p.ai_digest.startswith("Views up")


def test_reconcile_why_times_drops_contradicting_sentence():
    from src.services.generation.ai_execution import _reconcile_why_times
    slots = [
        # why claims "1 PM"/"lunch" but the slot fires at 18:01 (evening) → drop those
        {"time_ist": "18:01", "why": "Amazon electronics, avg views 504. The post time "
         "at 1 PM is beneficial during the lunch hour. Strong pick over Flipkart."},
        # why says "afternoon" but slot is evening → drop that sentence
        {"time_ist": "18:58", "why": "Flipkart home deal (529 views). Good earlier in "
         "the afternoon for browsers."},
        # matching day-part → keep untouched
        {"time_ist": "13:02", "why": "Electronics single; the afternoon window suits it."},
    ]
    _reconcile_why_times(slots)
    assert "1 PM" not in slots[0]["why"] and "lunch" not in slots[0]["why"].lower()
    assert "504" in slots[0]["why"]  # non-time reasoning preserved
    assert "afternoon" not in slots[1]["why"].lower()
    assert "529" in slots[1]["why"]
    assert "afternoon" in slots[2]["why"].lower()  # correct claim kept
