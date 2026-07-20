"""Coverage for the style→follower context signals feeding the planner:
- daily_style_by_day: per-IST-day owned style features (loot/media/emoji/coupon rates).
- style_follower_correlation: those features lined up with per-day net follower change,
  with median-split comparisons — correlational, sample-sized, empty-safe.
"""
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
    from src.db.models_growth_snapshot import DailySubscriberStat

    init_db()
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C")
        s.add(ch)
        s.flush()

        # 8 consecutive days ending 2026-06-30, 2 owned posts/day. The 4 recent days are
        # loot-heavy + media + more emojis and paired with HIGH net follower gains; the 4
        # older days are single-deal, text-only, LOW net — so a loot_share median split
        # must land loot-heavy days on the higher-net side.
        end = date(2026, 6, 30)
        for i in range(8):
            d = end - timedelta(days=i)
            loot = i < 4  # i=0..3 are the recent days
            at = datetime(d.year, d.month, d.day, 12, 0, tzinfo=timezone.utc)
            for j in range(2):
                p = Post(channel_id=ch.id, tg_message_id=i * 10 + j, posted_at=at,
                         collected_at=at, views=100, has_media=loot, text="deal " * (20 if loot else 5))
                s.add(p)
                s.flush()
                s.add(NormalizedPost(
                    source_id=p.id, source_type=SourceType.OWNED, normalized_at=at,
                    primary_merchant_key="amazon", is_multi_deal=loot, has_coupon=loot,
                    emojis=["🔥", "😍"] if loot else ["🔥"], cta_texts=["buy"] if loot else None))
            s.add(DailySubscriberStat(
                channel_id=ch.id, stat_date=d,
                subs_start=1000, subs_end=1000 + (20 if loot else 2),
                subs_joined=(22 if loot else 4), subs_left=2,
                subs_net=(20 if loot else 2)))
        s.flush()
    yield


def test_daily_style_by_day_features():
    from src.ai import context as ctx
    from src.db.session import session_scope

    with session_scope() as s:
        out = ctx.daily_style_by_day(s, days=8, end_day=date(2026, 6, 30))

    days = out["days"]
    assert len(days) == 8
    assert sum(d["posts"] for d in days) == 16
    by_date = {d["date"]: d for d in days}
    loot_day = by_date["2026-06-30"]          # i=0 -> loot
    single_day = by_date["2026-06-23"]        # i=7 -> single
    assert loot_day["loot_share"] == 1.0
    assert loot_day["media_rate"] == 1.0
    assert loot_day["emoji_density"] == 2.0
    assert single_day["loot_share"] == 0.0
    assert single_day["media_rate"] == 0.0
    assert single_day["emoji_density"] == 1.0


def test_style_follower_correlation_pairs_and_compares():
    from src.ai import context as ctx
    from src.db.session import session_scope

    with session_scope() as s:
        corr = ctx.style_follower_correlation(s, days=8, end_day=date(2026, 6, 30))

    assert corr["available"] is True
    assert corr["n_days"] == 8
    # every day row carries the merged follower delta
    assert all(r["followers_net"] is not None for r in corr["days"] if r.get("posts"))
    loot_cmp = next((c for c in corr["comparisons"] if c["feature"] == "loot_share"), None)
    assert loot_cmp is not None
    # loot-heavy days were seeded with the higher net follower gain
    assert loot_cmp["high_days_avg_net"] > loot_cmp["low_days_avg_net"]


def test_style_follower_correlation_empty_safe():
    from src.ai import context as ctx
    from src.db.session import session_scope

    with session_scope() as s:
        # a window well before any posting history: no paired days -> not available,
        # and daily_style_by_day must still return zero-post day rows, not crash.
        style = ctx.daily_style_by_day(s, days=5, end_day=date(2025, 1, 10))
        corr = ctx.style_follower_correlation(s, days=5, end_day=date(2025, 1, 10))

    assert [d["posts"] for d in style["days"]] == [0, 0, 0, 0, 0]
    assert corr["available"] is False
