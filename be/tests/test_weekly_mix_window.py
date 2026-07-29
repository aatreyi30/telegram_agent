"""The weekly plan's loot_deal_ratio (the 'Target mix' badge) must be computed from the
SAME 30-day window ending at the plan's week as the narrative's own grounding data
(full_briefing_context's post_type_performance_range) — not the all-time snapshot.
Regression for: the digest cited near-tied 30-day views ("loot 521 vs single 520, lean
into loot") while the Target mix badge showed single as the clear majority (57/43),
computed from a completely different, all-time-skewed window — two windows disagreeing
on the same plan, same class of bug already fixed for the daily deal-type split."""
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

        # RECENT 20 days (within the 30-day window ending today): LOOT posts get high
        # views (1000), SINGLE posts get low views (100) — loot clearly wins per-post
        # here. This is what the narrative's grounding data (and the fix) must read.
        base = datetime(today.year, today.month, today.day, 12, 0, tzinfo=timezone.utc)
        for i in range(20):
            is_loot = i % 2 == 0
            p = Post(channel_id=ch.id, tg_message_id=i, posted_at=base - timedelta(days=i),
                     collected_at=base, views=1000 if is_loot else 100)
            s.add(p)
            s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                                 normalized_at=base, primary_merchant_key="amazon",
                                 is_multi_deal=is_loot))

        # OLD 60 days (well outside the 30-day window, 250+ days back): the OPPOSITE skew
        # — SINGLE posts get high views (1000), LOOT posts get low views (100) — single
        # clearly wins per-post here. This dominates the ALL-TIME snapshot. If the bug
        # were still present, loot_deal_ratio would reflect THIS (single-favoring) skew
        # instead of the recent (loot-favoring) one.
        old_base = base - timedelta(days=250)
        for i in range(60):
            is_loot = i % 5 == 0
            p = Post(channel_id=ch.id, tg_message_id=1000 + i, posted_at=old_base - timedelta(days=i),
                     collected_at=old_base, views=100 if is_loot else 1000)
            s.add(p)
            s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                                 normalized_at=old_base, primary_merchant_key="amazon",
                                 is_multi_deal=is_loot))
    yield


def test_weekly_loot_ratio_uses_the_30_day_window_not_all_time(monkeypatch):
    from src.controllers import service

    monkeypatch.setattr(
        "src.ai.planner.generate_week_plan",
        lambda s, week_start=None, directive=None, end_day=None, **_kw: {
            "available": True, "digest": "Weekly digest.",
            "plan": {"loot_deal_ratio": None, "merchant_priorities": None,
                    "direction": "d", "daily_themes": None}},
    )
    r = service.regenerate_weekly()
    ratio = r["loot_deal_ratio"]
    # Recent 20 days: loot averages 1000 views/post, single averages 100 — loot clearly
    # wins per-post in the window that must drive this. The old 60-day history has the
    # OPPOSITE skew (single wins) and dominates the all-time snapshot — if the bug were
    # still present (all-time driving the ratio), loot would show as the MINORITY here.
    assert ratio["loot"] > ratio["deal"], ratio