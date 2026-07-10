"""Manual competitor onboarding: fast insert (create_competitor_record), the
slow 4-stage pipeline (run_onboarding_pipeline), and the POST /api/competitors
route that wires the two together via a FastAPI BackgroundTask."""
from __future__ import annotations

import os
import tempfile

import pytest

ADMIN_EMAIL = "admin@dealwing.local"
ADMIN_PW = "dealwing123"


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    os.environ["ADMIN_EMAIL"] = ADMIN_EMAIL
    os.environ["ADMIN_PASSWORD"] = ADMIN_PW
    os.environ["AUTH_SECRET"] = "test-secret"
    os.environ["SCHEDULERS_AUTOSTART"] = "false"  # never auto-run jobs during tests
    from src.config.settings import get_settings
    from src.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()

    from src.db.session import init_db

    init_db()
    yield


# ------------------------- create_competitor_record ------------------------- #
def test_create_competitor_record_sets_manual_fields():
    from src.controllers import service

    row = service.create_competitor_record("SomeCompetitor", "platform")
    assert row["username"] == "SomeCompetitor"
    assert row["category"] == "platform"
    assert row["discovered_via"] == "manual"
    assert row["verified_by"] == "manual"
    assert row["resolution_confidence"] == 1.0
    assert row["access_status"] == "available"


def test_create_competitor_record_strips_leading_at():
    from src.controllers import service

    row = service.create_competitor_record("@HandleWithAt", "channel")
    assert row["username"] == "HandleWithAt"


def test_create_competitor_record_idempotent_on_duplicate_username():
    from src.controllers import service

    first = service.create_competitor_record("DupCompetitor", "channel")
    second = service.create_competitor_record("DupCompetitor", "channel")
    assert first["id"] == second["id"]


def test_create_competitor_record_rejects_invalid_category():
    from src.controllers import service

    with pytest.raises(ValueError):
        service.create_competitor_record("BadCategoryCompetitor", "not_a_real_category")


# ------------------------- run_onboarding_pipeline ------------------------- #
# Patching JobRunner.run_collector (rather than each collector's .run()) skips
# JobRunner's own retry/backoff sleep on a raised exception, keeping the
# failure-survival test fast, while still exercising the real call surface
# run_onboarding_pipeline actually drives.
def test_run_onboarding_pipeline_calls_stages_in_order(monkeypatch):
    from src.controllers import service
    from src.services.collection.base import JobRunner

    calls: list[str] = []

    def fake_run_collector(self, collector, **kwargs):
        calls.append(collector.name)
        return None

    monkeypatch.setattr(JobRunner, "run_collector", fake_run_collector)

    service.create_competitor_record("PipelineOrder", "channel")
    service.run_onboarding_pipeline("PipelineOrder")

    assert calls == ["telegram_competitor", "link_resolution", "normalizer", "competitor_intel"]


def test_run_onboarding_pipeline_survives_a_stage_exception(monkeypatch):
    from src.controllers import service
    from src.services.collection.base import JobRunner

    calls: list[str] = []

    def fake_run_collector(self, collector, **kwargs):
        if collector.name == "telegram_competitor":
            raise RuntimeError("simulated Telegram rate limit")
        calls.append(collector.name)
        return None

    monkeypatch.setattr(JobRunner, "run_collector", fake_run_collector)

    service.create_competitor_record("PipelineFailure", "channel")
    service.run_onboarding_pipeline("PipelineFailure")  # must not raise

    assert calls == ["link_resolution", "normalizer", "competitor_intel"]


# ------------------------- POST /api/competitors ------------------------- #
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.db.org_seed import seed_org
    from src.db.session import session_scope
    from src.main import create_app

    app = create_app()  # runs init_db (migrations + tables) again — idempotent
    with session_scope() as s:
        seed_org(s)  # seeds the admin user with ADMIN_PASSWORD
    return TestClient(app)


@pytest.fixture(scope="module")
def token(client):
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    return r.json()["data"]["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_post_competitors_returns_record_and_starts_pipeline(client, token, monkeypatch):
    from src.controllers import service

    calls: list[str] = []
    monkeypatch.setattr(service, "run_onboarding_pipeline", lambda username: calls.append(username))

    resp = client.post("/api/competitors", headers=_auth(token),
                       json={"username": "RouteCompetitor", "category": "channel"})
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["username"] == "RouteCompetitor"
    assert body["category"] == "channel"
    assert body["pipeline_started"] is True
    assert calls == ["RouteCompetitor"]  # background task ran, real pipeline never called


def test_post_competitors_rejects_bad_category(client, token):
    resp = client.post("/api/competitors", headers=_auth(token),
                       json={"username": "BadCatRoute", "category": "nonsense"})
    assert resp.status_code == 400
    assert resp.json()["success"] is False
