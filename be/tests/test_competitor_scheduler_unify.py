from __future__ import annotations
import os, tempfile
from types import SimpleNamespace

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


def test_competitor_sync_job_uses_db_only(monkeypatch):
    """j_competitor_sync (src/controllers/schedulers.py — the live scheduler job,
    superseding the legacy CollectionScheduler removed in Phase 0.5) must iterate
    only DB-discovered Competitor.username rows, not env var competitors.
    """
    from src.db.session import session_scope
    from src.db.models import Competitor
    with session_scope() as s:
        s.add(Competitor(username="DbComp"))
        s.add(Competitor(username="AnotherComp"))

    import src.controllers.schedulers as sched

    seen = []

    class _FakeRunner:
        def run_collector(self, collector, **kw):
            seen.append(kw.get("target"))
            return SimpleNamespace(records_added=0)

    monkeypatch.setattr(sched, "_job_runner", lambda: _FakeRunner())
    sched.j_competitor_sync()

    assert "DbComp" in seen, "DB-discovered competitor missing from tick"
    assert "AnotherComp" in seen, "Second DB-discovered competitor missing from tick"
    assert len(seen) == 2, f"Expected 2 competitors, got {len(seen)}"


def test_competitor_sync_job_skips_monitoring_disabled(monkeypatch):
    """A competitor with monitoring_enabled=False must not be synced -- the
    per-competitor toggle (Settings > Competitors) is meant to stop the daily
    cron from re-collecting/re-profiling it forever."""
    from src.db.session import session_scope
    from src.db.models import Competitor
    with session_scope() as s:
        s.add(Competitor(username="StillMonitored", monitoring_enabled=True))
        s.add(Competitor(username="PausedComp", monitoring_enabled=False))

    import src.controllers.schedulers as sched

    seen = []

    class _FakeRunner:
        def run_collector(self, collector, **kw):
            seen.append(kw.get("target"))
            return SimpleNamespace(records_added=0)

    monkeypatch.setattr(sched, "_job_runner", lambda: _FakeRunner())
    sched.j_competitor_sync()

    assert "StillMonitored" in seen
    assert "PausedComp" not in seen, "monitoring_enabled=False competitor must be skipped"
