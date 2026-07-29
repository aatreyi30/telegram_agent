"""_grounded_weekly_summary (the deterministic fallback shown when the AI's own
weekly narrative fails fact-check) must use the SAME 30-day window as the rest of
the weekly plan, and must never assert a mix conclusion ("so the mix leans X") that
can contradict the plan's actual, possibly-steered loot_deal_ratio. Regression for a
real live bug: the fallback cited all-time numbers ("single deals out-perform loot,
so the mix leans single") on a page whose badge said "Loot 65%" per an active
"lean into loot boards" steer — a fallback that's supposed to be the honest,
non-contradictory read instead directly contradicted the plan around it."""
from __future__ import annotations

import os
import tempfile
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

    init_db()
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C")
        s.add(ch)
        s.flush()

        # RECENT 30 days (ending the anchor day, 2026-08-02): LOOT wins per-post here
        # (1000 vs 100).
        base = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
        for i in range(30):
            is_loot = i % 2 == 0
            p = Post(channel_id=ch.id, tg_message_id=i, posted_at=base - timedelta(days=i),
                     collected_at=base, views=1000 if is_loot else 100)
            s.add(p)
            s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                                 normalized_at=base, primary_merchant_key="amazon",
                                 is_multi_deal=is_loot))

        # OLD 60 days (250+ days back): the OPPOSITE skew (single wins), dominates the
        # all-time snapshot. If the bug were still present (all-time driving the
        # summary), it would say single out-performs loot instead.
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


def test_grounded_summary_uses_30_day_window_and_states_no_mix_conclusion():
    from src.controllers.service import _grounded_weekly_summary
    from src.db.session import session_scope

    with session_scope() as s:
        summary = _grounded_weekly_summary(s, end_day=date(2026, 8, 2))

    # Real 30-day numbers (loot wins) must appear, not the all-time (single-favoring)
    # snapshot dominated by the older 60-day history.
    assert "loot boards averaged 1,000 views" in summary or "loot boards averaged 1000 views" in summary
    assert "single deals'" in summary
    # Must never assert which way the mix leans — that's the plan's own decision
    # (possibly overridden by an operator steer), not this fallback's to make.
    assert "the mix leans" not in summary