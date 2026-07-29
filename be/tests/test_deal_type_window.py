"""The deal-type split (Plan page's 'Target posts' + 'Why') must learn from the SAME
30-day window as the displayed avg-views figure beside it — not the all-time growth-engine
snapshot. Regression for: operator saw "last 13 months of posting" in the Why when they
expected "30 days", the same window the views column already uses."""
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
        # 20 days of BOTH single and loot posts, all within the last 30 days, so the
        # windowed query has real data for both deal-types.
        base = datetime(today.year, today.month, today.day, 12, 0, tzinfo=timezone.utc)
        for i in range(20):
            p = Post(channel_id=ch.id, tg_message_id=i, posted_at=base - timedelta(days=i),
                     collected_at=base, views=100 + i)
            s.add(p)
            s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                                 normalized_at=base, primary_merchant_key="amazon",
                                 is_multi_deal=(i % 2 == 0)))
        # One OLD post (200 days back) so an all-time snapshot, if used, would report a
        # much longer span than 30 days — the split must NOT reach back this far.
        old = base - timedelta(days=200)
        p_old = Post(channel_id=ch.id, tg_message_id=999, posted_at=old,
                     collected_at=base, views=50)
        s.add(p_old)
        s.flush()
        s.add(NormalizedPost(source_id=p_old.id, source_type=SourceType.OWNED,
                             normalized_at=base, primary_merchant_key="amazon",
                             is_multi_deal=False))
    yield


def test_deal_type_split_uses_the_30_day_window_when_it_has_posts():
    from src.controllers.service import _today_details
    from src.db.session import session_scope
    from src.services.analytics.periods import ist_today

    with session_scope() as s:
        _windows, allocation, _merchants, _risks = _today_details(s, recommended_posts=10, day=ist_today())

    assert allocation, "expected a non-empty deal-type allocation"
    for a in allocation:
        assert a.get("source_kind") == "recent_30d", a