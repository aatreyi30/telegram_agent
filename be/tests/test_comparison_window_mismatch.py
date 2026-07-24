# be/tests/test_comparison_window_mismatch.py
"""Regression test: comparison.compare() must flag when an entity's observation
window is wildly different from owned's — comparing posts_per_day/avg_views
across a 40-day owned history and a 5-day competitor history looks
apples-to-apples but isn't, since each is computed over its own window."""
from __future__ import annotations
import os, tempfile
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
    from src.db.models import Channel, Post, Competitor, CompetitorPost
    from src.db.models_normalization import NormalizedPost, SourceType
    init_db()

    now = datetime.now(timezone.utc)
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="Owned", title="Owned", kind="owned")
        s.add(ch); s.flush()
        # owned: 15 posts spread across 40 days (a wide, real window)
        for i in range(15):
            p = Post(channel_id=ch.id, tg_message_id=1000 + i,
                     posted_at=now - timedelta(days=40 - i * (40 // 15)), views=100 + i,
                     text=f"owned {i}", collected_at=now)
            s.add(p); s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED, normalized_at=now))

        comp = Competitor(username="rival", title="Rival")
        s.add(comp); s.flush()
        # competitor: 12 posts spread across only 5 days (a thin, recent window)
        for i in range(12):
            s.add(CompetitorPost(competitor_id=comp.id, tg_message_id=2000 + i,
                                 posted_at=now - timedelta(days=5 - i * (5 / 12)), views=50 + i,
                                 text=f"rival {i}", collected_at=now))
    yield


def test_window_mismatch_flagged_when_histories_differ_wildly():
    from src.services.analytics.comparison import compare
    from src.db.session import session_scope

    with session_scope() as s:
        result = compare(s, window_days=60)  # window-filtered mode, re-queries raw posts

    owned = next(e for e in result["entities"] if e["is_owned"])
    rival = next(e for e in result["entities"] if not e["is_owned"])
    assert owned["window_days"] > rival["window_days"] * 2
    assert rival["window_mismatch"] is True
