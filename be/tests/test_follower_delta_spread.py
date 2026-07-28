"""follower_deltas_by_day spreads a sparse snapshot's net across its gap days — but only
within the displayed window — so a fortnight of growth doesn't read as a 1-day spike,
and nothing reaches back before week_start."""
from __future__ import annotations

import os
import tempfile
from datetime import date

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
    from src.db.models_growth_snapshot import DailySubscriberStat
    init_db()
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C"); s.add(ch); s.flush()
        # Sparse capture: 07-10, then a big jump captured on 07-24, then 07-27.
        s.add(DailySubscriberStat(channel_id=ch.id, stat_date=date(2026, 7, 10),
                                  subs_start=26506, subs_end=26506, subs_joined=0, subs_left=0, subs_net=0))
        s.add(DailySubscriberStat(channel_id=ch.id, stat_date=date(2026, 7, 24),
                                  subs_start=26506, subs_end=28470, subs_joined=1976, subs_left=12, subs_net=1964))
        s.add(DailySubscriberStat(channel_id=ch.id, stat_date=date(2026, 7, 27),
                                  subs_start=28470, subs_end=28564, subs_joined=114, subs_left=20, subs_net=94))
        s.flush()
        globals()["_CH"] = ch.id
    yield


def test_spread_bounded_to_window():
    from src.db.session import session_scope
    from src.ai.context import follower_deltas_by_day
    with session_scope() as s:
        d = follower_deltas_by_day(s, _CH, date(2026, 7, 21), date(2026, 7, 27))

    # No fake 1-day spike: the 1964 is spread over the window days up to the snapshot
    # (07-21..07-24 = 4 days), NOT dumped on Friday, and NOT reaching back to 07-10.
    assert d["2026-07-24"]["net"] == round(1964 / 4)          # ~491, not 1964
    assert d["2026-07-21"]["net"] == d["2026-07-24"]["net"]   # evenly spread across the 4
    assert all(f"2026-07-{day:02d}" in d for day in (21, 22, 23, 24))
    # nothing spread before the window start
    assert "2026-07-20" not in d and "2026-07-10" not in d
    # the second gap (07-25..07-27) carries 07-27's 94
    assert d["2026-07-27"]["net"] == round(94 / 3)            # ~31


def test_no_spike_over_1964_anywhere():
    from src.db.session import session_scope
    from src.ai.context import follower_deltas_by_day
    with session_scope() as s:
        d = follower_deltas_by_day(s, _CH, date(2026, 7, 21), date(2026, 7, 27))
    assert max(v["net"] for v in d.values()) < 1964          # the spike is gone