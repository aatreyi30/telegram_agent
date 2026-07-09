# be/tests/test_daily_report_aggregator.py
from __future__ import annotations
import os, tempfile
from datetime import date, datetime, timezone
import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    os.environ["OWNED_CHANNELS"] = "MyChannel"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db, session_scope
    from src.db.models import Channel, Post
    from src.db.models_normalization import NormalizedPost, SourceType
    init_db()
    # seed one owned channel + posts on an IST day
    from src.services.analytics.periods import IST
    from datetime import timedelta
    d = date(2026, 7, 6)
    base = datetime(d.year, d.month, d.day, 12, 0, tzinfo=IST).astimezone(timezone.utc)
    with session_scope() as s:
        ch = Channel(tg_channel_id=111, username="MyChannel", title="Mine", kind="owned")
        s.add(ch); s.flush()
        for i, v in enumerate([800, 4000, 1500]):
            p = Post(channel_id=ch.id, tg_message_id=1000 + i,
                     posted_at=base + timedelta(minutes=i), views=v,
                     reactions_total=10 * i, forwards=i, text=f"deal {i}",
                     collected_at=base)
            s.add(p)
            s.flush()
            # build_owned_report() now goes through day.py's canonical
            # Post->NormalizedPost(source_type=OWNED) join (same query used by
            # /day and /analytics) — every Post fixture needs a matching row or
            # it's invisible to the report, same as test_analytics_views.py.
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                                 normalized_at=base))
    yield


def test_build_owned_report_totals():
    from src.services.analytics.daily_report import build_owned_report
    from src.db.session import session_scope
    with session_scope() as s:
        rep = build_owned_report(s, date(2026, 7, 6))
        assert rep.posts_count == 3
        assert rep.views_total == 6300
        assert rep.views_max == 4000
        assert rep.views_min == 800


def test_run_daily_reports_persists_and_upserts():
    from src.services.analytics.daily_report import run_daily_reports
    from src.db.models_report import DailyChannelReport
    from src.db.session import session_scope
    from sqlalchemy import select, func
    with session_scope() as s:
        run_daily_reports(s, date(2026, 7, 6))
    with session_scope() as s:
        run_daily_reports(s, date(2026, 7, 6))  # second run must upsert, not duplicate
        n = s.scalar(select(func.count()).select_from(DailyChannelReport))
        assert n == 1
