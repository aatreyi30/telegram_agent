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


def test_campaign_plan_new_columns_roundtrip():
    from src.db.models_campaign import CampaignPlan, PlanType
    from src.db.session import session_scope
    from sqlalchemy import select
    with session_scope() as s:
        s.add(CampaignPlan(
            plan_type=PlanType.DAILY, title="AI day plan",
            target_date=date(2026, 7, 8), blueprint={"post_slots": []},
            expected_outcome={"electronics_views_pct": 15},
            confidence=0.6, generated_at=datetime.now(timezone.utc),
            ai_digest="Yesterday views up 12%.", cited_numbers=[2100, 980, 0.30],
            factcheck_status="passed", is_ai_generated=True,
            report_ids=[1, 2], adherence={"planned": 6, "published": 4},
            reconciliation={"note": "2 evening slots missed"},
        ))
    with session_scope() as s:
        p = s.scalars(select(CampaignPlan)).one()
        assert p.is_ai_generated is True
        assert p.factcheck_status == "passed"
        assert p.cited_numbers == [2100, 980, 0.30]
        assert p.adherence["published"] == 4
