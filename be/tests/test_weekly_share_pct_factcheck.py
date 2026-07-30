"""The weekly digest naturally cites a post-type share as a percentage ("single deals
account for 65% of your posts"), but post_type_performance's `share` field is a 0-1
fraction (0.65) — without a percentage-scaled twin in the fact-check pool, that
correct, grounded citation fails the numeric match (0.65 vs 65) and gets wrongly
flagged `warn`, exactly what a real digest hit live: single_deal share=0.647,
avg_views=523.8 cited as "524" (passes) and "65%" (was failing before this fix)."""
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

        # 20 single + 10 loot within the last 30 days -> single share = 20/30 = 0.667,
        # cited in prose as "67%" — a non-round percentage, same shape as the real
        # 0.647 -> "65%" case that surfaced this bug. Anchored at the plan's end_day
        # (Aug 2, not "today") so all 30 posts land inside the [end_day-29, end_day]
        # window generate_week_plan actually reads — anchoring a few days earlier
        # silently truncated the oldest posts out of the window.
        base = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
        for i in range(30):
            is_loot = i < 10
            p = Post(channel_id=ch.id, tg_message_id=i, posted_at=base - timedelta(days=i),
                     collected_at=base, views=500)
            s.add(p)
            s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                                 normalized_at=base, primary_merchant_key="amazon",
                                 is_multi_deal=is_loot))
    yield


def test_percent_formatted_share_citation_passes_factcheck(monkeypatch):
    from src.ai import planner

    # "67" is cited ONLY in the free-text digest — the plan's own structural numbers
    # (loot_deal_ratio, daily_themes shares) deliberately use DIFFERENT values, so a
    # pass here can only come from the fact-check pool actually containing a
    # percentage-scaled share, not from the AI's own self-valid structural JSON
    # accidentally also containing "67" (which would mask whether the real fix matters).
    canned = (
        "Single deals account for 67% of your posts this week.\n"
        "===PLAN===\n"
        '{"week_start":"2026-07-27","direction":"d","loot_deal_ratio":{"loot":40,"deal":60},'
        '"merchant_priorities":[],"daily_themes":[{"day":"mon","loot_share":0.4,'
        '"single_share":0.6,"posts_planned":10}],"why":"w","cited_numbers":[]}'
    )
    monkeypatch.setattr(planner.AIClient, "complete", lambda self, *a, **k: canned)

    from src.db.session import session_scope
    with session_scope() as s:
        res = planner.generate_week_plan(s, week_start=date(2026, 7, 27), end_day=date(2026, 8, 2))

    assert res["available"]
    # Before the fix: "67" (from "67%") never matched the raw fraction 0.667 in the
    # pool, so a fully-grounded citation was wrongly downgraded to `warn`.
    assert res["factcheck"]["status"] == "passed", res["factcheck"]