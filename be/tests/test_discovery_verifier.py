"""Discovery accuracy — stricter resolution gate + AI verifier (rescue plan Task 15).

Covers:
  * `verify_candidate` falls back to the deterministic heuristic when the AI
    layer is unavailable, and still picks the clearly-correct candidate.
  * `verify_candidate` rejects a weak sole/lead candidate rather than
    blindly trusting it (the accuracy bug this task fixes).
  * `resolve_username` wires the verifier in and records
    `resolution_confidence` / `verified_by` on the existing `Competitor` row.
"""
from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    os.environ["TELEGRAM_API_ID"] = "12345"
    os.environ["TELEGRAM_API_HASH"] = "test-hash"
    from src.config.settings import get_settings
    from src.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db

    init_db()
    yield


def test_verify_candidate_falls_back_to_heuristic_without_ai(monkeypatch):
    """Real candidates from `_search_name_variations` only carry
    `username`/`title`/`participants` — no `similarity`/`relevance`/`description`
    keys. verify_candidate must compute those itself and still pick the clear
    winner when the AI layer is unavailable."""
    import src.services.collection.discovery as disc
    from src.ai.client import AIClient

    monkeypatch.setattr(AIClient, "available", lambda self: (False, "no key"))

    cands = [
        {"username": "OfficialBrand", "title": "Brand Official", "participants": 5000},
        {"username": "IndiaDealsLoot", "title": "India Deals Loot", "participants": 100},
    ]
    username, conf, method = disc.verify_candidate("Brand", cands)
    assert username == "OfficialBrand"
    assert method == "heuristic"
    assert 0.0 <= conf <= 1.0


def test_verify_candidate_rejects_weak_only_match(monkeypatch):
    import src.services.collection.discovery as disc
    from src.ai.client import AIClient

    monkeypatch.setattr(AIClient, "available", lambda self: (False, "no key"))

    cands = [{"username": "IndiaDealsLoot", "title": "India Deals Loot", "participants": 50}]
    username, conf, method = disc.verify_candidate("Nykaa", cands)
    assert username is None  # weak, non-matching sole candidate is rejected, not accepted


def test_resolve_username_stores_confidence_and_verified_by(monkeypatch):
    """resolve_username must use verify_candidate's verdict and record
    resolution_confidence/verified_by on the existing Competitor row for the
    name being resolved, without storing a wrong guess when confidence is low."""
    import src.services.collection.discovery as disc
    from src.ai.client import AIClient
    from src.db.models import Competitor
    from src.db.session import session_scope
    from sqlalchemy import select

    monkeypatch.setattr(AIClient, "available", lambda self: (False, "no key"))
    monkeypatch.setattr(disc, "owned_handles", lambda: [], raising=False)
    monkeypatch.setattr(
        "src.services.collection.channels.owned_handles", lambda: [], raising=False
    )

    with session_scope() as s:
        s.add(Competitor(username="BrandCo", discovered_via="config"))

    async def _fake_search(settings, name, exclude, limit_per_query=10):
        return [
            {"username": "BrandCoOfficial", "title": "BrandCo Official", "participants": 8000},
            {"username": "RandomLootDeals", "title": "Random Loot Deals", "participants": 20},
        ]

    monkeypatch.setattr(disc, "_search_name_variations", _fake_search)

    result = disc.resolve_username("BrandCo")
    assert result is not None
    assert result["username"] == "BrandCoOfficial"
    assert result["resolution_confidence"] is not None
    assert result["verified_by"] == "heuristic"

    with session_scope() as s:
        comp = s.scalar(select(Competitor).where(Competitor.username == "BrandCo"))
        assert comp.resolution_confidence == result["resolution_confidence"]
        assert comp.verified_by == "heuristic"


def test_resolve_username_returns_none_and_does_not_store_low_confidence(monkeypatch):
    """A weak/ambiguous sole candidate must resolve to None — no wrong guess stored."""
    import src.services.collection.discovery as disc
    from src.ai.client import AIClient
    from src.db.models import Competitor
    from src.db.session import session_scope
    from sqlalchemy import select

    monkeypatch.setattr(AIClient, "available", lambda self: (False, "no key"))
    monkeypatch.setattr(
        "src.services.collection.channels.owned_handles", lambda: [], raising=False
    )

    with session_scope() as s:
        s.add(Competitor(username="WeakBrand", discovered_via="config"))

    async def _fake_search(settings, name, exclude, limit_per_query=10):
        return [{"username": "UnrelatedDealsChannel", "title": "Unrelated Deals Channel",
                  "participants": 30}]

    monkeypatch.setattr(disc, "_search_name_variations", _fake_search)

    result = disc.resolve_username("WeakBrand")
    assert result is None

    with session_scope() as s:
        comp = s.scalar(select(Competitor).where(Competitor.username == "WeakBrand"))
        assert comp.resolution_confidence is None
        assert comp.verified_by is None
