"""The daily subscriber-snapshot roll-up: a fresh count folds into that IST day's
DailySubscriberStat correctly — first observation seeds start from the prior day's end
(so a multi-day gap's growth isn't dropped), later observations accrue joined/left, and
spans_days records how many calendar days the delta actually covers."""
from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timezone

import pytest


@pytest.fixture(scope="module", autouse=True)
def _db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/t.db"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db, session_scope
    from src.db.models import Channel
    init_db()
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C"); s.add(ch); s.flush()
        globals()["_CH"] = ch.id
    yield


def _grab(day):
    from src.db.session import session_scope
    from sqlalchemy import select
    from src.db.models_growth_snapshot import DailySubscriberStat
    with session_scope() as s:
        return s.scalar(select(DailySubscriberStat).where(
            DailySubscriberStat.channel_id == _CH, DailySubscriberStat.stat_date == day))


def test_rollup_seeds_and_spans_gap():
    from src.db.session import session_scope
    from src.services.collection.telegram_owned import _upsert_daily_subscriber_stat
    now = datetime(2026, 7, 10, 0, 10, tzinfo=timezone.utc)

    # Day 1 (07-10): first-ever capture -> start == count, net 0, spans 1 day.
    with session_scope() as s:
        _upsert_daily_subscriber_stat(s, _CH, date(2026, 7, 10), 26506, now)
    r = _grab(date(2026, 7, 10))
    assert (r.subs_start, r.subs_end, r.subs_net, r.spans_days) == (26506, 26506, 0, 1)

    # Next capture is 14 days later (07-24): start seeds from 07-10's end, net is the
    # real change since then, and spans_days == 14 (so the UI knows it's not 1 day).
    with session_scope() as s:
        _upsert_daily_subscriber_stat(s, _CH, date(2026, 7, 24), 28470,
                                      datetime(2026, 7, 24, 0, 10, tzinfo=timezone.utc))
    r = _grab(date(2026, 7, 24))
    assert (r.subs_start, r.subs_end, r.subs_net) == (26506, 28470, 1964)
    assert r.spans_days == 14

    # A SECOND observation the same day accrues onto that day's row (no new row).
    with session_scope() as s:
        _upsert_daily_subscriber_stat(s, _CH, date(2026, 7, 24), 28480,
                                      datetime(2026, 7, 24, 6, 0, tzinfo=timezone.utc))
    r = _grab(date(2026, 7, 24))
    assert r.subs_end == 28480 and r.subs_joined == 1974  # 1964 + 10 more joins