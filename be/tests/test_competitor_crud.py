"""Competitor CRUD -- Update (category/title, username immutable) and Delete
(preview-unless-confirm, cascade in FK-dependency order). Mirrors the shape of
test_competitor_onboarding.py's Create tests and delete_channel's cascade
contract (see service.delete_channel)."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone

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


_cluster_seq = iter(range(1, 100_000))


def _make_cascade_data(username: str):
    """Insert a competitor plus one full chain of dependent rows (competitor
    post -> normalized post -> classification + extracted price/coupon/link,
    and a profile + benchmark) so delete_competitor's cascade has something
    real to remove. Returns the competitor id."""
    from src.db.models import Competitor, CompetitorPost
    from src.db.models_classification import PostClassification, PostTypeCluster
    from src.db.models_competitor_intel import CompetitorBenchmark, CompetitorProfile
    from src.db.models_normalization import (
        ExtractedCoupon, ExtractedLink, ExtractedPrice, NormalizedPost, SourceType)
    from src.db.session import session_scope

    now = datetime.now(timezone.utc)
    with session_scope() as s:
        comp = Competitor(username=username, category="channel",
                          discovered_via="manual", verified_by="manual",
                          resolution_confidence=1.0, access_status="available")
        s.add(comp)
        s.flush()

        cpost = CompetitorPost(competitor_id=comp.id, tg_message_id=1001,
                               posted_at=now, text="hello", collected_at=now)
        s.add(cpost)
        s.flush()

        norm = NormalizedPost(source_type=SourceType.COMPETITOR, source_id=cpost.id,
                              normalized_at=now)
        s.add(norm)
        s.flush()

        cluster = PostTypeCluster(cluster_index=next(_cluster_seq), size=1, centroid={},
                                  feature_means={}, fitted_at=now)
        s.add(cluster)
        s.flush()

        s.add(PostClassification(normalized_post_id=norm.id, cluster_id=cluster.id,
                                 classified_at=now))
        s.add(ExtractedPrice(normalized_post_id=norm.id, amount=99.0))
        s.add(ExtractedCoupon(normalized_post_id=norm.id, code="SAVE10"))
        s.add(ExtractedLink(normalized_post_id=norm.id, url="https://example.com/x"))
        s.add(CompetitorProfile(competitor_id=comp.id, username=username, computed_at=now))
        s.add(CompetitorBenchmark(competitor_id=comp.id, username=username,
                                  dimension="posts_per_day", computed_at=now))
        s.flush()
        return comp.id


def _row_counts(competitor_id: int) -> dict:
    from sqlalchemy import func, select
    from src.db.models import CompetitorPost
    from src.db.models_classification import PostClassification
    from src.db.models_competitor_intel import CompetitorBenchmark, CompetitorProfile
    from src.db.models_normalization import (
        ExtractedCoupon, ExtractedLink, ExtractedPrice, NormalizedPost, SourceType)
    from src.db.session import session_scope

    with session_scope() as s:
        post_ids = select(CompetitorPost.id).where(CompetitorPost.competitor_id == competitor_id)
        norm_ids = select(NormalizedPost.id).where(
            NormalizedPost.source_type == SourceType.COMPETITOR,
            NormalizedPost.source_id.in_(post_ids))

        def _count(model, *where):
            return s.scalar(select(func.count()).select_from(model).where(*where)) or 0

        return {
            "competitor_posts": _count(CompetitorPost, CompetitorPost.competitor_id == competitor_id),
            "normalized_posts": _count(NormalizedPost, NormalizedPost.source_type == SourceType.COMPETITOR,
                                       NormalizedPost.source_id.in_(post_ids)),
            "classifications": _count(PostClassification, PostClassification.normalized_post_id.in_(norm_ids)),
            "prices": _count(ExtractedPrice, ExtractedPrice.normalized_post_id.in_(norm_ids)),
            "coupons": _count(ExtractedCoupon, ExtractedCoupon.normalized_post_id.in_(norm_ids)),
            "links": _count(ExtractedLink, ExtractedLink.normalized_post_id.in_(norm_ids)),
            "profiles": _count(CompetitorProfile, CompetitorProfile.competitor_id == competitor_id),
            "benchmarks": _count(CompetitorBenchmark, CompetitorBenchmark.competitor_id == competitor_id),
        }


# ------------------------- competitors_list / competitors() ------------------------- #
def test_competitors_list_includes_id_for_unprofiled_row():
    from src.controllers import service

    row = service.create_competitor_record("ListShapeCompetitor", "platform")
    rows = service.competitors_list()
    match = next(r for r in rows if r["id"] == row["id"])
    assert match["username"] == "ListShapeCompetitor"
    assert match["category"] == "platform"
    assert "status" in match and "last_collected_at" in match and "posts" in match


def test_competitors_returns_competitors_key():
    from src.controllers import service

    body = service.competitors()
    assert "competitors" in body
    assert isinstance(body["competitors"], list)


# ------------------------- update_competitor ------------------------- #
def test_update_competitor_changes_category_and_title():
    from src.controllers import service

    row = service.create_competitor_record("UpdateMeCompetitor", "channel")
    result = service.update_competitor(row["id"], category="platform", title="New Title")
    assert result["ok"] is True
    assert result["category"] == "platform"
    assert result["title"] == "New Title"
    assert result["username"] == "UpdateMeCompetitor"  # unchanged


def test_update_competitor_rejects_bad_category():
    from src.controllers import service

    row = service.create_competitor_record("BadCatUpdateCompetitor", "channel")
    with pytest.raises(ValueError):
        service.update_competitor(row["id"], category="not_a_real_category")


def test_update_competitor_404_missing_id():
    from src.controllers import service

    result = service.update_competitor(999999, title="whatever")
    assert result["ok"] is False


def test_update_competitor_has_no_username_param():
    """username is immutable -- the function signature must not even accept it."""
    from src.controllers import service
    import inspect

    params = inspect.signature(service.update_competitor).parameters
    assert "username" not in params


# ------------------------- delete_competitor ------------------------- #
def test_delete_competitor_preview_then_cascade():
    from src.controllers import service

    target_id = _make_cascade_data("DeleteMeCompetitor")
    other_id = _make_cascade_data("OtherUntouchedCompetitor")

    preview = service.delete_competitor(target_id, confirm=False)
    assert preview["ok"] is False
    assert preview["requires_confirm"] is True
    would = preview["would_delete"]
    assert would["username"] == "DeleteMeCompetitor"
    assert would["competitor_posts"] == 1
    assert would["normalized_posts"] == 1
    assert would["profiles"] == 1
    assert would["benchmarks"] == 1

    # preview must NOT have deleted anything yet
    assert _row_counts(target_id)["competitor_posts"] == 1

    result = service.delete_competitor(target_id, confirm=True)
    assert result["ok"] is True
    deleted_counts = _row_counts(target_id)
    assert all(v == 0 for v in deleted_counts.values()), deleted_counts

    # the other competitor's full chain must be untouched
    other_counts = _row_counts(other_id)
    assert other_counts == {
        "competitor_posts": 1, "normalized_posts": 1, "classifications": 1,
        "prices": 1, "coupons": 1, "links": 1, "profiles": 1, "benchmarks": 1,
    }

    from src.db.models import Competitor
    from src.db.session import session_scope
    with session_scope() as s:
        assert s.get(Competitor, target_id) is None
        assert s.get(Competitor, other_id) is not None


def test_delete_competitor_404_missing_id():
    from src.controllers import service

    result = service.delete_competitor(999999, confirm=True)
    assert result["ok"] is False
    assert "error" in result


# ------------------------- routes ------------------------- #
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


def test_patch_competitors_route_updates_and_ignores_username(client, token):
    from src.controllers import service

    row = service.create_competitor_record("RouteUpdateCompetitor", "channel")
    resp = client.patch(f"/api/competitors/{row['id']}", headers=_auth(token),
                        json={"category": "platform", "title": "Routed Title",
                              "username": "ShouldBeIgnored"})
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["category"] == "platform"
    assert body["title"] == "Routed Title"
    assert body["username"] == "RouteUpdateCompetitor"  # unchanged despite the extra field


def test_patch_competitors_route_bad_category_400(client, token):
    from src.controllers import service

    row = service.create_competitor_record("RouteBadCatCompetitor", "channel")
    resp = client.patch(f"/api/competitors/{row['id']}", headers=_auth(token),
                        json={"category": "nonsense"})
    assert resp.status_code == 400
    assert resp.json()["success"] is False


def test_patch_competitors_route_404(client, token):
    resp = client.patch("/api/competitors/999999", headers=_auth(token), json={"title": "x"})
    assert resp.status_code == 404


def test_delete_competitors_route_requires_confirm_then_deletes(client, token):
    target_id = _make_cascade_data("RouteDeleteCompetitor")

    preview = client.delete(f"/api/competitors/{target_id}", headers=_auth(token))
    assert preview.status_code == 409
    assert preview.json()["success"] is False

    confirmed = client.delete(f"/api/competitors/{target_id}?confirm=true", headers=_auth(token))
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["ok"] is True
    assert _row_counts(target_id)["competitor_posts"] == 0


def test_delete_competitors_route_404(client, token):
    resp = client.delete("/api/competitors/999999?confirm=true", headers=_auth(token))
    assert resp.status_code == 404


def test_get_competitors_route_returns_id(client, token):
    from src.controllers import service

    row = service.create_competitor_record("GetRouteCompetitor", "channel")
    resp = client.get("/api/competitors", headers=_auth(token))
    assert resp.status_code == 200
    rows = resp.json()["data"]["competitors"]
    match = next(r for r in rows if r["id"] == row["id"])
    assert match["username"] == "GetRouteCompetitor"
