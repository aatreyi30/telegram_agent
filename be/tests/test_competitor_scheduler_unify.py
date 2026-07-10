from __future__ import annotations
import os, tempfile
import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    # No COMPETITOR_CHANNELS env var needed anymore - competitors come from DB only
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db
    init_db()
    yield


def test_competitors_tick_uses_db_only(monkeypatch):
    """_competitors must iterate only DB-discovered Competitor.username rows,
    not env var competitors (env var dependency removed).
    """
    from src.db.session import session_scope
    from src.db.models import Competitor
    with session_scope() as s:
        s.add(Competitor(username="DbComp"))
        s.add(Competitor(username="AnotherComp"))

    import src.services.collection.scheduler as mod
    sched = mod.CollectionScheduler()
    seen = []
    monkeypatch.setattr(sched.runner, "run_collector", lambda collector, **kw: seen.append(kw.get("target")))
    sched._competitors()

    assert "DbComp" in seen, "DB-discovered competitor missing from tick"
    assert "AnotherComp" in seen, "Second DB-discovered competitor missing from tick"
    assert len(seen) == 2, f"Expected 2 competitors, got {len(seen)}"
