# be/tests/test_link_resolution.py
"""Async link-resolution engine — cache dedup, domain-capture fallback, and
explicit failure bookkeeping (see be/src/services/collection/link_resolution.py).

Uses httpx.MockTransport so the AsyncClient built inside the engine never hits
the real network; the transport is injected via monkeypatch on the module's
`httpx.AsyncClient` symbol.
"""

from __future__ import annotations

import functools
import itertools
import os
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

_source_id_seq = itertools.count(1)


@pytest.fixture()
def isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db
    init_db()
    yield


def _make_post_and_links(urls: list[str], domains: list[str | None] | None = None) -> list[int]:
    """Insert one NormalizedPost + one ExtractedLink per url; returns link ids."""
    from src.db.models_normalization import ExtractedLink, NormalizedPost, SourceType
    from src.db.session import session_scope

    domains = domains or [None] * len(urls)
    ids: list[int] = []
    with session_scope() as s:
        post = NormalizedPost(
            source_type=SourceType.OWNED, source_id=next(_source_id_seq),
            normalized_at=datetime.now(timezone.utc),
        )
        s.add(post)
        s.flush()
        for url, domain in zip(urls, domains):
            link = ExtractedLink(
                normalized_post_id=post.id, url=url, domain=domain, is_shortlink=True,
            )
            s.add(link)
            s.flush()
            ids.append(link.id)
    return ids


def _patch_transport(monkeypatch, handler):
    """Force LinkResolutionEngine's httpx.AsyncClient(...) calls to use a
    MockTransport, regardless of the http2/limits/timeout kwargs it passes."""
    from src.services.collection import link_resolution

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        link_resolution.httpx, "AsyncClient", functools.partial(httpx.AsyncClient, transport=transport)
    )


def _fake_job():
    """A minimal, persisted CollectionJob row so event-bus persistence (which
    FKs on job_id) succeeds, mirroring how JobRunner really invokes a collector."""
    from src.db.models import CollectionJob
    from src.db.session import session_scope

    with session_scope() as s:
        job = CollectionJob(job_type="link_resolution")
        s.add(job)
        s.flush()
        job_id = job.id
    return SimpleNamespace(id=job_id)


# --------------------------------------------------------------------------- #
# (a) in-run cache prevents a second network call for a duplicate URL
# --------------------------------------------------------------------------- #
def test_duplicate_url_resolved_only_once_per_run(isolated_db, monkeypatch):
    from src.services.collection.link_resolution import LinkResolutionEngine
    from src.db.models_normalization import ExtractedLink
    from src.db.session import session_scope

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, request=request)

    _patch_transport(monkeypatch, handler)

    # NOT a self-domain (grbn.in/grabon.in/whatsapp/telegram) — a shortlink
    # that dead-ends on one of those must NOT be captured as a merchant (see
    # test_self_domain_never_captured_as_merchant below); this test is only
    # about the once-per-run cache + the generic domain-capture fallback.
    shared_url = "https://myshortlink.io/dup123"
    ids = _make_post_and_links([shared_url, shared_url])

    engine = LinkResolutionEngine(limit=100)
    engine.run(_fake_job())

    assert len(calls) == 1, f"expected exactly one network call, got {calls}"

    with session_scope() as s:
        links = [s.get(ExtractedLink, i) for i in ids]
        for link in links:
            assert link.resolved_url == shared_url
            assert link.merchant_key  # domain-capture fallback classified it


# --------------------------------------------------------------------------- #
# (b) domain-capture fallback creates/increments a DiscoveredDomain row and
#     sets a merchant_key for a resolved URL outside the static registry
# --------------------------------------------------------------------------- #
def test_domain_capture_fallback_creates_discovered_domain(isolated_db, monkeypatch):
    from src.services.collection.link_resolution import LinkResolutionEngine
    from src.db.models_normalization import DiscoveredDomain, ExtractedLink
    from src.db.session import session_scope

    shortlink_url = "https://grbn.in/nb001"
    final_url = "https://www.nutrabay.com/products/whey-protein"

    def handler(request: httpx.Request) -> httpx.Response:
        # simulate any grbn.in shortlink 302-redirecting to the merchant landing page
        if str(request.url).startswith("https://grbn.in/"):
            return httpx.Response(302, headers={"Location": final_url}, request=request)
        return httpx.Response(200, request=request)

    _patch_transport(monkeypatch, handler)

    ids = _make_post_and_links([shortlink_url])

    engine = LinkResolutionEngine(limit=100)
    engine.run(_fake_job())

    with session_scope() as s:
        link = s.get(ExtractedLink, ids[0])
        assert link.merchant_key == "nutrabay"
        assert link.resolution_status == "resolved"

        discovered = s.get(DiscoveredDomain, "nutrabay.com")
        assert discovered is not None
        assert discovered.merchant_key == "nutrabay"
        assert discovered.count == 1
        assert discovered.sample_post_id is not None

    # run again with a second, different link landing on the same domain —
    # the count should increment rather than duplicate the row.
    ids2 = _make_post_and_links(["https://grbn.in/nb002"])
    engine.run(_fake_job())
    with session_scope() as s:
        discovered = s.get(DiscoveredDomain, "nutrabay.com")
        assert discovered.count == 2


# --------------------------------------------------------------------------- #
# (c) a simulated failure increments resolution_attempts and records the error,
#     without touching resolved_url / merchant_key
# --------------------------------------------------------------------------- #
def test_resolution_failure_is_recorded_and_retryable(isolated_db, monkeypatch):
    from src.services.collection.link_resolution import LinkResolutionEngine
    from src.db.models_normalization import ExtractedLink
    from src.db.session import session_scope

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _patch_transport(monkeypatch, handler)

    ids = _make_post_and_links(["https://grbn.in/broken1"])

    engine = LinkResolutionEngine(limit=100)
    engine.run(_fake_job())

    with session_scope() as s:
        link = s.get(ExtractedLink, ids[0])
        assert link.resolution_status == "failed"
        assert link.resolution_attempts == 1
        assert link.resolution_error and "connection refused" in link.resolution_error
        assert link.resolved_url is None
        assert link.merchant_key is None

    # a second run retries it (attempts < cap) and increments again
    engine.run(_fake_job())
    with session_scope() as s:
        link = s.get(ExtractedLink, ids[0])
        assert link.resolution_attempts == 2
        assert link.resolution_status == "failed"


# --------------------------------------------------------------------------- #
# (d) self-domains (platform's own domain, WhatsApp, Telegram) never become a
#     merchant_key — neither via the raw-domain pre-fetch shortcut nor via the
#     domain-capture fallback when a shortlink dead-ends without redirecting.
# --------------------------------------------------------------------------- #
def test_self_domain_never_captured_as_merchant(isolated_db, monkeypatch):
    from src.services.collection.link_resolution import LinkResolutionEngine
    from src.db.models_normalization import ExtractedLink
    from src.db.session import session_scope

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        # No redirect — simulates a dead/self-referential shortlink.
        return httpx.Response(200, request=request)

    _patch_transport(monkeypatch, handler)

    # A raw link whose *known* domain is a self/utility domain (e.g. a post
    # sharing a WhatsApp channel link directly) must short-circuit BEFORE any
    # network call.
    whatsapp_ids = _make_post_and_links(
        ["https://whatsapp.com/channel/abc123"], domains=["whatsapp.com"]
    )
    # A grbn.in shortlink that never actually redirects anywhere (dead-ends on
    # itself) must NOT be captured as a fake "grbn" merchant — but it DOES
    # still require the network fetch (grbn.in is the platform's own
    # shortener and must always be followed).
    grbn_ids = _make_post_and_links(["https://grbn.in/dead1"], domains=["grbn.in"])

    engine = LinkResolutionEngine(limit=100)
    engine.run(_fake_job())

    assert calls == ["https://grbn.in/dead1"], (
        f"whatsapp.com link should have skipped the network call entirely, got {calls}"
    )

    with session_scope() as s:
        wa_link = s.get(ExtractedLink, whatsapp_ids[0])
        assert wa_link.merchant_key is None
        assert wa_link.resolution_status == "no_match"
        assert wa_link.resolved_url == "https://whatsapp.com/channel/abc123"

        grbn_link = s.get(ExtractedLink, grbn_ids[0])
        assert grbn_link.merchant_key is None
        assert grbn_link.resolution_status == "no_match"


def test_raw_shortener_domain_still_resolves_through_redirect(isolated_db, monkeypatch):
    """grbn.in must be excluded from becoming a merchant itself, but a raw
    link on grbn.in that DOES redirect to a real merchant must still resolve
    normally — the pre-fetch self-domain shortcut must not swallow it."""
    from src.services.collection.link_resolution import LinkResolutionEngine
    from src.db.models_normalization import ExtractedLink
    from src.db.session import session_scope

    final_url = "https://www.nutrabay.com/products/whey-protein"

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith("https://grbn.in/"):
            return httpx.Response(302, headers={"Location": final_url}, request=request)
        return httpx.Response(200, request=request)

    _patch_transport(monkeypatch, handler)

    ids = _make_post_and_links(["https://grbn.in/nb003"], domains=["grbn.in"])

    engine = LinkResolutionEngine(limit=100)
    engine.run(_fake_job())

    with session_scope() as s:
        link = s.get(ExtractedLink, ids[0])
        assert link.merchant_key == "nutrabay"
        assert link.resolution_status == "resolved"
