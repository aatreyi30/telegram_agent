"""Global 'auto-discover new competitors' org toggle (Settings > Org).

`discover_competitors()` must skip cleanly (no crash, no Telegram call) when
the org has `auto_discover_competitors=False` in its settings JSON, and must
default to enabled when the org row or the setting is missing entirely --
today's behaviour must never silently stop working.
"""
from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture(scope="function", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    os.environ["SCHEDULERS_AUTOSTART"] = "false"
    from src.config.settings import get_settings
    from src.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db

    init_db()
    yield


def _seed_org_setting(auto_discover: bool | None) -> None:
    """Insert the default Organization row with `auto_discover_competitors`
    set (or omitted entirely when `auto_discover` is None, to test the
    missing-setting default)."""
    from src.config.settings import get_settings
    from src.db.models_org import Organization
    from src.db.session import session_scope

    settings = dict(**{})
    key = get_settings().org_key
    org_settings = {} if auto_discover is None else {"auto_discover_competitors": auto_discover}
    with session_scope() as s:
        s.add(Organization(key=key, name="Test Org", settings=org_settings))


def test_auto_discover_allowed_by_default_when_no_org_row():
    from src.services.collection.discovery import _auto_discover_allowed
    assert _auto_discover_allowed() is True


def test_auto_discover_allowed_by_default_when_setting_missing():
    _seed_org_setting(None)
    from src.services.collection.discovery import _auto_discover_allowed
    assert _auto_discover_allowed() is True


def test_auto_discover_disabled_when_setting_false():
    _seed_org_setting(False)
    from src.services.collection.discovery import _auto_discover_allowed
    assert _auto_discover_allowed() is False


def test_auto_discover_enabled_when_setting_true():
    _seed_org_setting(True)
    from src.services.collection.discovery import _auto_discover_allowed
    assert _auto_discover_allowed() is True


def test_discover_competitors_returns_disabled_status_without_telegram_creds():
    """Gate must be checked BEFORE the Telegram-credentials check, so a
    disabled org never even needs MTProto configured to short-circuit."""
    _seed_org_setting(False)
    # deliberately no TELEGRAM_API_ID/HASH set -- would normally raise
    from src.services.collection.discovery import discover_competitors
    result = discover_competitors(max_add=5)
    assert result == {"candidates": 0, "added": 0, "top": [], "status": "disabled"}


def test_scheduler_job_reports_limited_when_discovery_disabled(monkeypatch):
    import src.controllers.schedulers as sched

    monkeypatch.setattr(
        "src.services.collection.discovery.discover_competitors",
        lambda max_add=5: {"candidates": 0, "added": 0, "top": [], "status": "disabled"},
    )
    result = sched.j_competitor_discover()
    assert result["status"] == "limited"
    assert result["processed"] == 0


def test_scheduler_job_still_reports_normally_when_enabled(monkeypatch):
    import src.controllers.schedulers as sched

    monkeypatch.setattr(
        "src.services.collection.discovery.discover_competitors",
        lambda max_add=5: {"candidates": 3, "added": 2, "top": ["a", "b"]},
    )
    result = sched.j_competitor_discover()
    assert result.get("status") is None or result.get("status") != "limited"
    assert result["processed"] == 2
