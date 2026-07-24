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
    from src.db.session import init_db, session_scope
    from src.db.models_campaign import CampaignPlan, PlanType
    init_db()
    with session_scope() as s:
        s.add(CampaignPlan(
            plan_type=PlanType.DAILY, title="AI day plan", target_date=date(2026, 7, 8),
            blueprint={"post_slots": [], "emphasis": "push electronics"},
            confidence=0.6, generated_at=datetime.now(timezone.utc),
            is_ai_generated=True, ai_digest="Yesterday views up 12%.",
            factcheck_status="passed"))
    yield


def test_digest_service_returns_latest_ai_plan():
    from src.controllers.service import digest
    d = digest()
    assert d["available"] is True
    assert d["digest"] == "Yesterday views up 12%."
    assert d["factcheck_status"] == "passed"
