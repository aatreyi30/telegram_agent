from __future__ import annotations
import os, tempfile
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


def test_competitor_resolution_columns():
    from src.db.models import Competitor
    from src.db.session import session_scope
    from sqlalchemy import select
    with session_scope() as s:
        s.add(Competitor(username="SomeBrand", title="Some Brand",
                         resolution_confidence=0.82, verified_by="ai"))
    with session_scope() as s:
        c = s.scalars(select(Competitor)).one()
        assert c.resolution_confidence == 0.82
        assert c.verified_by == "ai"
