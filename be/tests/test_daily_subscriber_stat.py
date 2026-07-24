"""Tests for the incremental DailySubscriberStat upsert + the rewritten growth()
service (joined/left/net from daily rollups, no growth-rate projection)."""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timezone


def _fresh_db():
    """Each test gets its own isolated sqlite file so channel selection in
    get_growth() (picks the top owned channel) can't collide across tests."""
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/growth.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db

    init_db()


def test_upsert_creates_then_accumulates_joined_and_left():
    _fresh_db()
    from sqlalchemy import select
    from src.db.models import Channel
    from src.db.models_growth_snapshot import DailySubscriberStat, ParticipantSnapshot
    from src.db.session import session_scope
    from src.services.collection.telegram_owned import _upsert_daily_subscriber_stat

    with session_scope() as s:
        ch = Channel(tg_channel_id=101, username="growthch", title="G", kind="owned")
        s.add(ch)
        s.flush()
        channel_id = ch.id

    day = date(2026, 7, 1)
    t0 = datetime(2026, 7, 1, 1, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 7, 1, 2, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 7, 1, 3, 0, tzinfo=timezone.utc)

    # first observation of the day: seeds subs_start/end, no joined/left yet
    with session_scope() as s:
        _upsert_daily_subscriber_stat(s, channel_id, day, 1000, t0)
        s.add(ParticipantSnapshot(channel_id=channel_id, captured_at=t0, count=1000))

    with session_scope() as s:
        row = s.scalar(select(DailySubscriberStat).where(
            DailySubscriberStat.channel_id == channel_id, DailySubscriberStat.stat_date == day))
        assert row.subs_start == 1000
        assert row.subs_end == 1000
        assert row.subs_joined == 0
        assert row.subs_left == 0
        assert row.subs_net == 0

    # count increases -> joined
    with session_scope() as s:
        _upsert_daily_subscriber_stat(s, channel_id, day, 1030, t1)
        s.add(ParticipantSnapshot(channel_id=channel_id, captured_at=t1, count=1030))

    # count decreases -> left
    with session_scope() as s:
        _upsert_daily_subscriber_stat(s, channel_id, day, 1010, t2)
        s.add(ParticipantSnapshot(channel_id=channel_id, captured_at=t2, count=1010))

    with session_scope() as s:
        row = s.scalar(select(DailySubscriberStat).where(
            DailySubscriberStat.channel_id == channel_id, DailySubscriberStat.stat_date == day))
        assert row.subs_start == 1000
        assert row.subs_end == 1010
        assert row.subs_joined == 30      # 1000 -> 1030
        assert row.subs_left == 20        # 1030 -> 1010
        assert row.subs_net == 10         # 1010 - 1000
        # sqlite drops tzinfo on round-trip; compare on the naive-UTC wall clock value
        got = row.updated_at if row.updated_at.tzinfo else row.updated_at.replace(tzinfo=timezone.utc)
        assert got == t2


def test_upsert_flags_a_collection_gap_instead_of_hiding_it():
    """Regression test for the confirmed bug: a multi-day silent gap between two
    DailySubscriberStat rows dumped the ENTIRE gap's growth onto the resumption
    day with no way to tell it apart from a real single-day spike. spans_days
    must record the real gap width, and get_growth must surface has_collection_gap."""
    _fresh_db()
    from sqlalchemy import select
    from src.db.models import Channel
    from src.db.models_growth_snapshot import DailySubscriberStat
    from src.db.session import session_scope
    from src.services.collection.telegram_owned import _upsert_daily_subscriber_stat
    from src.services.analytics.growth import get_growth

    with session_scope() as s:
        ch = Channel(tg_channel_id=303, username="gapch", title="Gap", kind="owned")
        s.add(ch)
        s.flush()
        channel_id = ch.id

    day1 = date(2026, 7, 10)
    day2 = date(2026, 7, 24)  # 14 days later — a real collection gap
    t1 = datetime(2026, 7, 10, 6, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 7, 24, 6, 0, tzinfo=timezone.utc)

    with session_scope() as s:
        _upsert_daily_subscriber_stat(s, channel_id, day1, 26506, t1)
        _upsert_daily_subscriber_stat(s, channel_id, day2, 28468, t2)

    with session_scope() as s:
        row = s.scalar(select(DailySubscriberStat).where(
            DailySubscriberStat.channel_id == channel_id, DailySubscriberStat.stat_date == day2))
        assert row.spans_days == 14
        assert row.subs_joined == 1962  # still the real total — just now labeled honestly

        g = get_growth(s)
        assert g["has_collection_gap"] is True
        assert g["days"] == 15  # real elapsed calendar span, not the 2-row count
        gap_row = next(d for d in g["daily"] if d["date"] == "2026-07-24")
        assert gap_row["spans_days"] == 14


def test_get_growth_shape_and_date_filter():
    _fresh_db()
    from datetime import date as date_cls
    from src.db.models import Channel
    from src.db.models_growth_snapshot import ParticipantSnapshot
    from src.db.session import session_scope
    from src.services.collection.telegram_owned import _upsert_daily_subscriber_stat
    from src.services.analytics.growth import get_growth

    with session_scope() as s:
        ch = Channel(tg_channel_id=202, username="growthch2", title="G2", kind="owned")
        s.add(ch)
        s.flush()
        channel_id = ch.id

        d1 = date_cls(2026, 6, 1)
        d2 = date_cls(2026, 6, 2)
        t1a = datetime(2026, 6, 1, 6, 0, tzinfo=timezone.utc)
        t1b = datetime(2026, 6, 1, 18, 0, tzinfo=timezone.utc)
        t2a = datetime(2026, 6, 2, 6, 0, tzinfo=timezone.utc)
        t2b = datetime(2026, 6, 2, 18, 0, tzinfo=timezone.utc)

        # day 1: two collection cycles, count rises 500 -> 510 (joined 10)
        _upsert_daily_subscriber_stat(s, channel_id, d1, 500, t1a)
        s.add(ParticipantSnapshot(channel_id=channel_id, captured_at=t1a, count=500))
        _upsert_daily_subscriber_stat(s, channel_id, d1, 510, t1b)
        s.add(ParticipantSnapshot(channel_id=channel_id, captured_at=t1b, count=510))
        # day 2: two collection cycles, count rises 510 -> 530 (joined 20)
        _upsert_daily_subscriber_stat(s, channel_id, d2, 510, t2a)
        s.add(ParticipantSnapshot(channel_id=channel_id, captured_at=t2a, count=510))
        _upsert_daily_subscriber_stat(s, channel_id, d2, 530, t2b)
        s.add(ParticipantSnapshot(channel_id=channel_id, captured_at=t2b, count=530))

    with session_scope() as s:
        full = get_growth(s)
        assert full["available"] is True
        assert full["current"] == 530
        assert full["joined"] == 30   # 10 (day 1) + 20 (day 2)
        assert full["left"] == 0
        assert full["net"] == 30
        assert full["days"] == 2
        assert "growth_rate_pct" not in full
        assert "growth_per_day" not in full
        assert full["daily"][0]["date"] == "2026-06-01"
        assert full["daily"][0]["subs_end"] == 510
        assert full["daily"][0]["joined"] == 10
        assert full["daily"][1]["joined"] == 20

        # narrowing the date window must NOT change "current" (still the true latest)
        narrow = get_growth(s, date_cls(2026, 6, 1), date_cls(2026, 6, 1))
        assert narrow["current"] == 530
        assert narrow["days"] == 1
        assert narrow["joined"] == 10  # only day 1 in range
