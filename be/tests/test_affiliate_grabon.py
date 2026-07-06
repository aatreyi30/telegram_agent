"""Affiliate provider tests — GrabOn URL rules, fallbacks, and provider selection.

URL transforms are pure (no network). The shortener is exercised with an injected
fake so the fallback contract is verified without hitting GrabOn's live endpoint.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.services.affiliate.base import AffiliateResult
from src.services.affiliate.generic import GenericAffiliateProvider
from src.services.affiliate.grabon import GrabOnAffiliateProvider, _extract_short_url


def _settings():
    return SimpleNamespace(
        grabon_shortener_url="https://shortner-api.grabon.com/api/url/shorten",
        grabon_amazon_tag="tlg022-21",
        grabon_flipkart_params="affid=bh7162&affExtParam1=1005&affExtParam2=gb",
        affiliate_provider="grabon",
        affiliate_provider_name="grabon",
    )


# ------------------------- Amazon rule ------------------------- #
def test_amazon_extracts_dp_id_and_drops_other_params():
    p = GrabOnAffiliateProvider(_settings())
    url = "https://www.amazon.in/AYSIS-Transparent-Organizer/dp/B0H416WF2T?ref=abc&th=1"
    aff, notes = p.build_affiliate_url(url, "amazon")
    assert aff == "https://www.amazon.in/dp/B0H416WF2T/?tag=tlg022-21"
    assert notes == []


def test_amazon_without_dp_falls_back():
    p = GrabOnAffiliateProvider(_settings())
    aff, notes = p.build_affiliate_url("https://www.amazon.in/some-search?k=phone", "amazon")
    assert aff is None
    assert notes and "clean URL" in notes[0]


# ------------------------- Flipkart rule ------------------------- #
def test_flipkart_strips_query_and_appends_params():
    p = GrabOnAffiliateProvider(_settings())
    url = "https://www.flipkart.com/product-name/p/itm27131dac551f8?pid=XXXXX&lid=YYYY"
    aff, notes = p.build_affiliate_url(url, "flipkart")
    assert aff == ("https://www.flipkart.com/product-name/p/itm27131dac551f8"
                   "?affid=bh7162&affExtParam1=1005&affExtParam2=gb")
    assert notes == []


def test_unknown_merchant_has_no_rule():
    p = GrabOnAffiliateProvider(_settings())
    aff, notes = p.build_affiliate_url("https://www.nykaa.com/x/p/123", "nykaa")
    assert aff is None
    assert "No GrabOn affiliate rule" in notes[0]


# ------------------------- merchant detection ------------------------- #
def test_detects_merchant_from_host_when_not_given():
    p = GrabOnAffiliateProvider(_settings())
    assert p._detect_merchant("https://www.amazon.in/dp/B01", None) == "amazon"
    assert p._detect_merchant("https://www.flipkart.com/x/p/itm1", None) == "flipkart"
    assert p._detect_merchant("https://example.com/x", None) is None


# ------------------------- shortener + fallback ------------------------- #
def test_generate_uses_short_url_when_shortener_succeeds(monkeypatch):
    p = GrabOnAffiliateProvider(_settings())
    monkeypatch.setattr(p, "shorten", lambda aff: ("https://grbn.in/abc123", []))
    res = p.generate("https://www.amazon.in/x/dp/B0H416WF2T?th=1", "amazon")
    assert res.final_url == "https://grbn.in/abc123"
    assert res.shortened is True
    assert res.affiliate_url == "https://www.amazon.in/dp/B0H416WF2T/?tag=tlg022-21"


def test_generate_falls_back_to_affiliate_url_when_shortener_fails(monkeypatch):
    p = GrabOnAffiliateProvider(_settings())
    monkeypatch.setattr(p, "shorten", lambda aff: (None, ["Shortener call failed (Timeout)"]))
    res = p.generate("https://www.flipkart.com/x/p/itm27131dac551f8?pid=Z", "flipkart")
    # never blocks posting: falls back to the affiliate URL
    assert res.short_url is None
    assert res.final_url == res.affiliate_url
    assert res.final_url.endswith("?affid=bh7162&affExtParam1=1005&affExtParam2=gb")
    assert res.shortened is False


def test_final_url_last_resort_is_original():
    # no affiliate rule + no short url -> original URL, still posts
    res = AffiliateResult(original_url="https://nykaa.com/x", merchant_key="nykaa",
                          affiliate_url=None, short_url=None, provider="grabon", shortened=False)
    assert res.final_url == "https://nykaa.com/x"


def test_extract_short_url_handles_nested_and_flat():
    assert _extract_short_url({"shortUrl": "https://grbn.in/a"}) == "https://grbn.in/a"
    assert _extract_short_url({"data": {"short_url": "https://grbn.in/b"}}) == "https://grbn.in/b"
    assert _extract_short_url("https://grbn.in/c") == "https://grbn.in/c"
    assert _extract_short_url({"status": "ok", "code": 200}) is None


# ------------------------- provider selection ------------------------- #
def test_registry_selects_grabon_only_when_configured():
    from src.services.affiliate.registry import get_affiliate_provider

    grab = get_affiliate_provider(settings=SimpleNamespace(
        affiliate_provider_name="grabon", grabon_shortener_url="x", grabon_amazon_tag="t",
        grabon_flipkart_params="p", grabon_shorten_all=True))
    assert grab.name == "grabon"
    gen = get_affiliate_provider(settings=SimpleNamespace(affiliate_provider_name="generic"))
    assert isinstance(gen, GenericAffiliateProvider)


def test_registry_reads_org_settings_first():
    from src.services.affiliate.registry import get_affiliate_provider

    org = SimpleNamespace(affiliate_provider="grabon", settings={
        "grabon_shortener_url": "https://s/x", "grabon_amazon_tag": "tlg022-21",
        "grabon_flipkart_params": "affid=bh7162", "grabon_shorten_all": True})
    prov = get_affiliate_provider(org=org)
    assert prov.name == "grabon" and prov.amazon_tag == "tlg022-21"


def test_generic_provider_is_passthrough():
    res = GenericAffiliateProvider().generate("https://www.amazon.in/dp/B01", "amazon")
    assert res.final_url == "https://www.amazon.in/dp/B01"
    assert res.shortened is False and res.affiliate_url is None
