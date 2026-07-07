from __future__ import annotations
import os, tempfile
import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    os.environ["COMPETITOR_CHANNELS"] = "EnvComp"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db
    init_db()
    yield


def test_competitors_tick_unions_db_and_env(monkeypatch):
    """_competitors must iterate the union of env competitor_channels and
    DB-discovered Competitor.username rows, not only the env list.

    NOTE: a naive substring check for "Competitor" in the source (as sketched
    in the plan) trivially passes because `_competitors` already references
    `CompetitorCollector`, which contains the substring "Competitor". This
    test instead drives real behavior: it seeds a DB-only competitor and
    asserts the tick actually dispatches to it alongside the env-configured
    one.
    """
    from src.db.session import session_scope
    from src.db.models import Competitor
    with session_scope() as s:
        s.add(Competitor(username="DbComp"))

    import src.services.collection.scheduler as mod
    sched = mod.CollectionScheduler()
    seen = []
    monkeypatch.setattr(sched.runner, "run_collector", lambda collector, **kw: seen.append(kw.get("target")))
    sched._competitors()

    assert "EnvComp" in seen, "env-configured competitor missing from tick"
    assert "DbComp" in seen, "_competitors still ignores DB-discovered competitors"
