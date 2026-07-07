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
    from src.db.session import init_db
    init_db()
    yield


def test_report_row_roundtrip_and_uniqueness():
    from src.db.models_report import DailyChannelReport, ReportSourceType
    from src.db.session import session_scope
    from sqlalchemy import select
    with session_scope() as s:
        s.add(DailyChannelReport(
            channel_id=None, source_type=ReportSourceType.OWNED,
            report_date=date(2026, 7, 6),
            posts_count=6, deals_posted=5, merchants_featured=3,
            views_total=12000, views_avg=2000.0, views_median=1900.0,
            views_max=4000, views_min=800,
            reactions_total=120, forwards_total=45, engagement_rate=0.013,
            subs_start=1000, subs_end=1010, subs_net=10,
            type_mix={"single": 4, "collection": 2},
            category_mix={"electronics": 3, "fashion": 2},
            posting_hours={"12": 2, "19": 2},
            best_category="electronics", worst_category="fashion",
            computed_at=datetime.now(timezone.utc), data_completeness=1.0,
        ))
    with session_scope() as s:
        row = s.scalars(select(DailyChannelReport)).one()
        assert row.views_max == 4000
        assert row.type_mix["single"] == 4
        assert row.source_type == ReportSourceType.OWNED
