"""A bot-blocked link is not a dead link.

Ajio/Amazon/Myntra answer 403 to any datacentre IP while serving real shoppers fine.
`_http_ok` used to call that a "dead link", so the pre-publish gate marked every post
`blocked_stale` and NOTHING could ever publish for those merchants. Verified against
the live pipeline: both real drafts blocked on `dead link (403)`.
"""

from __future__ import annotations

import httpx
import pytest

from src.services.generation import revalidate


def _fake_client(monkeypatch, head_status, get_status=None):
    """Stub httpx.Client so no network is touched. Records whether GET was retried."""
    calls = {"head": 0, "get": 0}

    class _R:
        def __init__(self, code): self.status_code = code

    class _C:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def head(self, url):
            calls["head"] += 1
            return _R(head_status)
        def get(self, url):
            calls["get"] += 1
            return _R(get_status if get_status is not None else head_status)

    monkeypatch.setattr(revalidate.httpx, "Client", lambda **kw: _C())
    return calls


@pytest.mark.parametrize("code", [403, 405, 429])
def test_blocked_codes_are_alive(monkeypatch, code):
    """The regression that blocked every post: these must NOT read as dead."""
    _fake_client(monkeypatch, code)
    ok, reason = revalidate._http_ok("https://www.ajio.com/p/702281001003")
    assert ok is True, f"{code} treated as dead -> every post blocks: {reason}"
    assert reason is None


@pytest.mark.parametrize("code", [403, 405, 429])
def test_blocked_codes_do_not_waste_a_get_retry(monkeypatch, code):
    calls = _fake_client(monkeypatch, code)
    revalidate._http_ok("https://x.test/p")
    assert calls["get"] == 0, "a bot-block shouldn't be retried with GET"


@pytest.mark.parametrize("code", [404, 410, 500, 503])
def test_genuinely_dead_links_still_block(monkeypatch, code):
    """The gate must still do its job — this is what stops stale/dead deals going out."""
    _fake_client(monkeypatch, code)
    ok, reason = revalidate._http_ok("https://x.test/gone")
    assert ok is False
    assert f"dead link ({code})" == reason


def test_head_rejected_but_get_serves(monkeypatch):
    """Some merchants 400 a HEAD yet serve GET — that link is alive."""
    calls = _fake_client(monkeypatch, head_status=400, get_status=200)
    ok, _ = revalidate._http_ok("https://x.test/p")
    assert ok is True and calls["get"] == 1


def test_ok_status_passes(monkeypatch):
    _fake_client(monkeypatch, 200)
    assert revalidate._http_ok("https://x.test/p") == (True, None)


def test_unreachable_host_blocks(monkeypatch):
    def _boom(**kw):
        raise httpx.ConnectError("no route")
    monkeypatch.setattr(revalidate.httpx, "Client", _boom)
    ok, reason = revalidate._http_ok("https://x.test/p")
    assert ok is False and "unreachable" in reason
