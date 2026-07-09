"""Tests for the new view/join "by source" plumbing added for Task Group 4:
- OwnedChannelCollector._upsert_source_rows (upsert-by-day-and-source, overwrite
  semantics since Telegram's graph is already a daily rollup)
- growth.compute_growth's view_sources/follower_sources, gated on can_view_stats

No Telethon/network involved — these exercise only the DB-facing pure logic.
"""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timezone


def _fresh_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/broadcast_stats.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db

    init_db()


def test_upsert_source_rows_creates_then_overwrites():
    _fresh_db()
    from sqlalchemy import select
    from src.db.models import Channel
    from src.db.models_growth_snapshot import DailyViewSource
    from src.db.session import session_scope
    from src.services.collection.telegram_owned import OwnedChannelCollector

    with session_scope() as s:
        ch = Channel(tg_channel_id=301, username="bstats", title="B", kind="owned")
        s.add(ch)
        s.flush()
        channel_id = ch.id

    d1 = date(2026, 7, 1)
    rows = [(d1, "search", 100), (d1, "channels", 40)]
    with session_scope() as s:
        OwnedChannelCollector._upsert_source_rows(s, DailyViewSource, channel_id, rows, "views")

    with session_scope() as s:
        got = {
            r.source_label: r.views
            for r in s.scalars(select(DailyViewSource).where(DailyViewSource.channel_id == channel_id))
        }
        assert got == {"search": 100, "channels": 40}

    # a resync overwrites in place rather than accumulating
    with session_scope() as s:
        OwnedChannelCollector._upsert_source_rows(
            s, DailyViewSource, channel_id, [(d1, "search", 150)], "views"
        )

    with session_scope() as s:
        rows_db = s.scalars(
            select(DailyViewSource).where(DailyViewSource.channel_id == channel_id)
        ).all()
        assert len(rows_db) == 2  # still just search + channels, no duplicate row
        by_label = {r.source_label: r.views for r in rows_db}
        assert by_label["search"] == 150
        assert by_label["channels"] == 40


def test_compute_growth_source_breakdown_gated_on_can_view_stats():
    _fresh_db()
    from src.db.models import Channel
    from src.db.models_growth_snapshot import DailyJoinSource, DailyViewSource
    from src.db.session import session_scope
    from src.services.analytics.growth import compute_growth

    with session_scope() as s:
        ch = Channel(tg_channel_id=302, username="bstats2", title="B2", kind="owned",
                      can_view_stats=True)
        s.add(ch)
        s.flush()
        channel_id = ch.id

        d1 = date(2026, 7, 1)
        d2 = date(2026, 7, 2)
        s.add(DailyViewSource(channel_id=channel_id, stat_date=d1, source_label="search", views=100))
        s.add(DailyViewSource(channel_id=channel_id, stat_date=d2, source_label="search", views=120))
        s.add(DailyViewSource(channel_id=channel_id, stat_date=d1, source_label="channels", views=30))
        s.add(DailyJoinSource(channel_id=channel_id, stat_date=d1, source_label="search", joins=5))

    with session_scope() as s:
        out = compute_growth(s, channel_id, can_view_stats=True)
        assert out["view_sources"]["totals"] == {"search": 220, "channels": 30}
        assert out["view_sources"]["daily"]["2026-07-01"] == {"search": 100, "channels": 30}
        assert out["view_sources"]["daily"]["2026-07-02"] == {"search": 120}
        assert out["follower_sources"]["totals"] == {"search": 5}

        # gated off entirely when can_view_stats is False, regardless of underlying data
        off = compute_growth(s, channel_id, can_view_stats=False)
        assert off["view_sources"] is None
        assert off["follower_sources"] is None


def test_get_growth_reads_can_view_stats_from_channel():
    _fresh_db()
    from src.db.models import Channel
    from src.db.models_growth_snapshot import DailyViewSource
    from src.db.session import session_scope
    from src.services.analytics.growth import get_growth

    with session_scope() as s:
        ch = Channel(tg_channel_id=303, username="bstats3", title="B3", kind="owned",
                      can_view_stats=False)
        s.add(ch)
        s.flush()
        channel_id = ch.id
        s.add(DailyViewSource(channel_id=channel_id, stat_date=date(2026, 7, 1),
                               source_label="search", views=10))

    with session_scope() as s:
        out = get_growth(s)
        # no DailySubscriberStat rows at all -> the "unavailable" early-return branch,
        # which must still carry the (gated-off) source fields
        assert out["available"] is False
        assert out["view_sources"] is None
        assert out["follower_sources"] is None
