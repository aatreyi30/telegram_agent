# be/tests/test_context_report_getters.py
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
    from src.db.models_report import DailyChannelReport, ReportSourceType
    init_db()
    with session_scope() as s:
        for i, v in enumerate([1000, 2000, 3000]):
            s.add(DailyChannelReport(
                channel_id=None, source_type=ReportSourceType.OWNED,
                report_date=date(2026, 7, 4 + i), posts_count=5,
                views_total=v, views_avg=float(v / 5), views_max=v, views_min=100,
                computed_at=datetime.now(timezone.utc), data_completeness=1.0))
    yield


def test_daily_reports_newest_first():
    from src.ai.context import daily_reports
    from src.db.session import session_scope
    with session_scope() as s:
        rows = daily_reports(s, days=8)
        assert len(rows) == 3
        assert rows[0]["report_date"] == "2026-07-06"
        assert rows[0]["views_total"] == 3000


def test_report_baseline_mean():
    from src.ai.context import report_baseline
    from src.db.session import session_scope
    with session_scope() as s:
        b = report_baseline(s, days=30)
        assert b["views_total"] == 2000  # mean of 1000,2000,3000
