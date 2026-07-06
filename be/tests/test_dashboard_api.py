"""DealWing API tests — auth, protected endpoints, pagination, users/org (TestClient)."""

from __future__ import annotations

import os
import tempfile

import pytest

ADMIN_EMAIL = "admin@dealwing.local"
ADMIN_PW = "dealwing123"


@pytest.fixture(scope="module")
def client():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/api.db"
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

    from fastapi.testclient import TestClient

    from src.main import create_app
    from src.db.org_seed import seed_org
    from src.db.session import session_scope

    app = create_app()          # runs init_db (migrations + tables)
    with session_scope() as s:
        seed_org(s)             # seeds the admin user with ADMIN_PASSWORD
    return TestClient(app)


@pytest.fixture(scope="module")
def token(client):
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    return r.json()["data"]["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _data(resp):
    """Unwrap the { success, data, error } envelope."""
    return resp.json()["data"]


# ------------------------- auth ------------------------- #
def test_login_success_and_failure(client):
    ok = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    assert ok.status_code == 200 and ok.json()["success"] is True and "token" in _data(ok)
    bad = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"})
    assert bad.status_code == 401 and bad.json()["success"] is False


def test_protected_endpoints_require_auth(client):
    for path in ["/api/overview", "/api/insights", "/api/analytics", "/api/drafts",
                 "/api/queue", "/api/job", "/api/users", "/api/org"]:
        assert client.get(path).status_code == 401, path


def test_me_returns_user(client, token):
    r = client.get("/api/auth/me", headers=_auth(token))
    assert r.status_code == 200 and _data(r)["email"] == ADMIN_EMAIL
    assert _data(r)["role"] == "owner"


# ------------------------- data + pagination ------------------------- #
def test_data_endpoints_ok_with_token(client, token):
    for path in ["/api/overview", "/api/insights", "/api/analytics", "/api/competitors",
                 "/api/merchants", "/api/plans"]:
        assert client.get(path, headers=_auth(token)).status_code == 200, path


def test_pagination_shape(client, token):
    r = client.get("/api/drafts", params={"page": 1, "page_size": 5}, headers=_auth(token))
    body = _data(r)
    assert r.status_code == 200
    assert set(body) >= {"items", "total", "page", "page_size", "pages"}
    assert body["page"] == 1 and body["page_size"] == 5


def test_api_day_validates_date(client, token):
    assert client.get("/api/day", params={"date": "bad"}, headers=_auth(token)).status_code == 400
    assert client.get("/api/day", params={"date": "2026-06-15"}, headers=_auth(token)).status_code == 200


def test_data_range_and_analytics_filter(client, token):
    dr = client.get("/api/data-range", headers=_auth(token))
    assert dr.status_code == 200 and set(_data(dr)) == {"min", "max"}
    # analytics accepts a start/end window and reports it back in `window`
    r = client.get("/api/analytics", params={"start": "2026-06-01", "end": "2026-06-30"},
                   headers=_auth(token))
    assert r.status_code == 200 and "window" in _data(r)
    # bad dates -> 400
    assert client.get("/api/analytics", params={"start": "nope"}, headers=_auth(token)).status_code == 400


def test_api_day_defaults_to_latest(client, token):
    # no date -> backend resolves the latest collected day (never crashes on "today")
    r = client.get("/api/day", headers=_auth(token))
    assert r.status_code == 200
    assert "available" in _data(r)


# ------------------------- users + org ------------------------- #
def test_users_crud_owner_only(client, token):
    # create
    created = client.post("/api/users", headers=_auth(token),
                          json={"name": "Editor", "email": "editor@x.com",
                                "password": "secret1", "role": "editor"})
    assert created.status_code == 200, created.text
    uid = _data(created)["user"]["id"]
    # list shows both
    users = _data(client.get("/api/users", headers=_auth(token)))
    assert any(u["email"] == "editor@x.com" for u in users)
    # patch role
    patched = client.patch(f"/api/users/{uid}", headers=_auth(token), json={"role": "viewer"})
    assert patched.status_code == 200 and _data(patched)["user"]["role"] == "viewer"
    # delete
    assert client.delete(f"/api/users/{uid}", headers=_auth(token)).status_code == 200
    # ensure gone
    assert not any(u["id"] == uid for u in _data(client.get("/api/users", headers=_auth(token))))


def test_cannot_delete_last_owner(client, token):
    me = _data(client.get("/api/auth/me", headers=_auth(token)))
    r = client.delete(f"/api/users/{me['id']}", headers=_auth(token))
    assert r.status_code == 400   # can't delete own / last owner


def test_org_get_and_patch(client, token):
    got = client.get("/api/org", headers=_auth(token))
    assert got.status_code == 200 and "settings" in _data(got)
    patched = client.patch("/api/org", headers=_auth(token),
                           json={"name": "GrabOn Renamed", "settings": {"grabon_amazon_tag": "tlg999-21"}})
    assert patched.status_code == 200
    assert _data(patched)["org"]["settings"]["grabon_amazon_tag"] == "tlg999-21"


def test_change_password_flow(client, token):
    bad = client.post("/api/auth/change-password", headers=_auth(token),
                      json={"old_password": "nope", "new_password": "brandnew1"})
    assert bad.status_code == 400
    # correct old password
    ok = client.post("/api/auth/change-password", headers=_auth(token),
                     json={"old_password": ADMIN_PW, "new_password": "brandnew1"})
    assert ok.status_code == 200
    # revert so other tests/logins keep working within module
    client.post("/api/auth/change-password", headers=_auth(token),
                json={"old_password": "brandnew1", "new_password": ADMIN_PW})


def test_openapi_docs(client):
    assert client.get("/api/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_job_stop_and_token_module():
    from src.auth.tokens import issue_token, verify_token
    from src.controllers.jobs import JobManager, _Stopped

    assert verify_token(issue_token(7)) == 7
    assert verify_token("garbage") is None
    m = JobManager()
    assert m.request_stop() is False
    m.state = "running"
    assert m.request_stop() is True
    with pytest.raises(_Stopped):
        m._checkpoint()
