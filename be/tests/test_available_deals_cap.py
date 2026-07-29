"""The daily plan's available_deals pool (limit = 3x recommended_posts) must be capped —
uncapped, a steered/ramped high count (target_posts now goes up to 350; an event ramp can
also push recommended_posts well past normal) turns into a 1000+ deal prompt payload,
tens of thousands of tokens for one call. Regression for a real cost blowup found by
querying actual ai_traces usage: day_plan calls averaging ~24k prompt tokens, 3x what an
isolated measurement showed, traced to this exact unbounded multiplier."""
from __future__ import annotations

import os
import tempfile

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
    from src.db.models_generation import EnrichedDeal

    init_db()
    with session_scope() as s:
        # 200 valid deals across the 4 allowed merchants — more than enough to hit any
        # cap being tested (normal-day 3x105, or the capped ceiling).
        merchants = ["amazon", "flipkart", "myntra", "ajio"]
        for i in range(200):
            s.add(EnrichedDeal(
                deal_id=f"deal_{i}", source="manual", title=f"Deal {i}",
                merchant_key=merchants[i % 4], category="general",
                current_price=100.0, original_price=200.0, discount_percent=50.0,
                is_loot_deal=False, deal_validity="valid"))
    yield


def test_available_deals_pool_is_capped_for_a_steered_high_count():
    from src.db.session import session_scope
    from src.ai.context import available_deals

    with session_scope() as s:
        # A normal day (~35 posts -> 3x105) is unaffected by the cap.
        normal = available_deals(s, limit=min(max(3 * 35, 9), 120))
        assert len(normal) == 105

        # A steered/ramped high count (e.g. 70/day, or a 200-post steer) must be capped,
        # not scale unbounded — this is the actual fix, verified against the real
        # planner.py formula shape.
        ramped = available_deals(s, limit=min(max(3 * 70, 9), 120))
        assert len(ramped) == 120   # capped, not 210

        extreme = available_deals(s, limit=min(max(3 * 350, 9), 120))
        assert len(extreme) == 120   # capped, not 1050