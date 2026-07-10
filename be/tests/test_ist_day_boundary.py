# be/tests/test_ist_day_boundary.py
"""Regression coverage for the IST/UTC day-boundary bug: a post posted late enough
in UTC to actually fall on the *next* IST calendar day was getting counted on the
wrong day by some consumers (day.py, analytics total_posts) but not others
(posting_trajectory), producing a real reported symptom — /plan/weekly showed 49
posts for a Wednesday while /day and /analytics showed 50 for the same date.

Root cause: `datetime(y, m, d, tzinfo=IST)` bound directly into a SQLite query
loses its tzinfo (SQLAlchemy's SQLite driver ignores it), so the WHERE clause
silently became a UTC-day filter instead of an IST-day filter — a 5.5h shift.
"""
from __future__ import annotations
import os, tempfile
from datetime import date, datetime, timezone
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
        ch = Channel(tg_channel_id=222, username="Boundary", title="Boundary", kind="owned")
        s.add(ch)
        s.flush()

        # 2026-07-08 18:34:39 UTC == 2026-07-09 00:04:39 IST — genuinely belongs to
        # the Wednesday->Thursday boundary: true IST day is July 9, NOT July 8.
        boundary_utc = datetime(2026, 7, 8, 18, 34, 39, tzinfo=timezone.utc)
        p = Post(channel_id=ch.id, tg_message_id=6627, posted_at=boundary_utc,
                  views=123, collected_at=boundary_utc)
        s.add(p)
        s.flush()
        s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                             normalized_at=boundary_utc))

        # An unambiguous mid-day post on July 8 IST, so July-8 queries aren't just
        # "empty" — they should see this one and NOT the boundary post.
        midday_utc = datetime(2026, 7, 8, 10, 0, 0, tzinfo=timezone.utc)  # 15:30 IST July 8
        p2 = Post(channel_id=ch.id, tg_message_id=6628, posted_at=midday_utc,
                   views=45, collected_at=midday_utc)
        s.add(p2)
        s.flush()
        s.add(NormalizedPost(source_id=p2.id, source_type=SourceType.OWNED,
                             normalized_at=midday_utc))
    yield


def test_ist_day_bounds_utc_converts_correctly():
    from src.services.analytics.periods import ist_day_bounds_utc, IST

    start, end = ist_day_bounds_utc(date(2026, 7, 8))
    # IST midnight July 8 == 18:30 UTC July 7; IST midnight July 9 == 18:30 UTC July 8.
    assert start == datetime(2026, 7, 7, 18, 30, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 8, 18, 30, tzinfo=timezone.utc)
    # The boundary post (18:34:39 UTC) must fall OUTSIDE this window.
    boundary = datetime(2026, 7, 8, 18, 34, 39, tzinfo=timezone.utc)
    assert not (start <= boundary < end)


def test_to_ist_is_correct_regardless_of_system_local_timezone():
    from src.services.analytics.periods import to_ist

    naive_utc_wallclock = datetime(2026, 7, 8, 18, 34, 39)  # what SQLite hands back
    ist = to_ist(naive_utc_wallclock)
    assert ist.date() == date(2026, 7, 9)
    assert (ist.hour, ist.minute) == (0, 4)


def test_day_view_excludes_boundary_post_from_july_8():
    from src.db.session import session_scope
    from src.services.analytics.day import summarize

    with session_scope() as s:
        result = summarize(s, date(2026, 7, 8))
    assert result["available"] is True
    assert result["posts"] == 1  # only the midday post — NOT the boundary one


def test_day_view_includes_boundary_post_on_july_9():
    from src.db.session import session_scope
    from src.services.analytics.day import summarize

    with session_scope() as s:
        result = summarize(s, date(2026, 7, 9))
    assert result["available"] is True
    assert result["posts"] == 1  # the boundary post now correctly lands here


def test_posting_trajectory_agrees_with_day_view():
    from src.db.session import session_scope
    from src.ai.context import posting_trajectory

    with session_scope() as s:
        traj = posting_trajectory(s, days=3, end_day=date(2026, 7, 9))
    by_date = {d["date"]: d["posts"] for d in traj["days"]}
    assert by_date["2026-07-08"] == 1
    assert by_date["2026-07-09"] == 1


def test_analytics_total_posts_agrees_with_day_view():
    from src.db.session import session_scope
    from src.services.analytics import views as vv
    from src.services.analytics.periods import ist_day_bounds_utc

    with session_scope() as s:
        start, end = ist_day_bounds_utc(date(2026, 7, 8))
        result = vv.compute(s, start=start, end=end)
    # This is exactly the reported bug: total_posts must match /day and
    # /plan/weekly (1), not silently include the next IST day's post (2).
    assert result["total_posts"] == 1
    assert result["timeline"][-1]["label"] == "2026-07-08"
    assert result["timeline"][-1]["n"] == 1
