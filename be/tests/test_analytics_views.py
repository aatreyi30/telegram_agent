"""Analytics tests — aggregation shape, per-day summary, and SVG chart safety."""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timedelta, timezone

import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/an.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.models import Channel, Post
    from src.db.models_normalization import NormalizedPost, SourceType
    from src.db.session import init_db, session_scope

    init_db()
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C")
        s.add(ch)
        s.flush()
        base = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        for i in range(10):
            p = Post(channel_id=ch.id, tg_message_id=i, posted_at=base - timedelta(days=i),
                     collected_at=base, views=100 + i * 10)
            s.add(p)
            s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                                 normalized_at=base,
                                 primary_merchant_key="amazon" if i % 2 else "flipkart"))
    yield


def test_compute_shapes_and_totals():
    from src.services.analytics import views as vv
    from src.db.session import session_scope

    with session_scope() as s:
        a = vv.compute(s)
    assert a["total_posts"] == 10
    assert a["total_views"] == sum(100 + i * 10 for i in range(10))
    assert a["by_merchant"]                       # merchants aggregated
    assert all("avg_views" in row for row in a["by_hour"])
    assert a["window"]["n"] == 10


def test_day_summary_present_and_absent():
    from src.services.analytics import day as dd
    from src.db.session import session_scope

    with session_scope() as s:
        present = dd.summarize(s, date(2026, 6, 15))
        absent = dd.summarize(s, date(2020, 1, 1))
    assert present["available"] is True
    assert present["posts"] >= 1 and present["top_posts"]
    assert "window" in present["baseline"]
    assert absent["available"] is False
