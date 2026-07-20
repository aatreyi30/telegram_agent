"""Merchant registry — facts sourced directly from the Data Validation Matrix.

This seeds the ``merchants`` table so the whole system can *represent* every
target merchant (including the BLOCKED ones) with an honest access verdict,
without ever fabricating data for merchants that cannot be collected.

Access status legend (SourceAccessStatus):
  available — confirmed collectable (a MerchantSource exists)
  partial   — collectable only with operator-supplied input / credentials
  blocked   — confirmed NOT collectable; no source; never fabricate
"""

from __future__ import annotations

from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Merchant, SourceAccessStatus

# key, display, domains, collector_id, access_status, notes
MERCHANT_SEED: list[dict] = [
    {
        "key": "amazon",
        "display_name": "Amazon",
        "domains": ["amazon.in", "amzn.to", "amzn.in", "link.amazon"],
        "collector": "amazon_creators_api",
        "access_status": SourceAccessStatus.PARTIAL,
        "access_notes": (
            "Amazon Creators API (replaced PA-API 2026-05-15). Requires an "
            "active Associates account with qualifying sales + credentials. "
            "Request contract must be confirmed against current Creators API "
            "docs before enabling in production."
        ),
    },
    {
        "key": "flipkart",
        "display_name": "Flipkart",
        "domains": [
            "flipkart.com", "fkrt.cc", "fkrt.it", "fkrt.co", "fkrt.site",
            "fkrt.to", "dl.flipkart.com", "fktr.cc", "fktr.in",
        ],
        "collector": "flipkart_affiliate_api",
        "access_status": SourceAccessStatus.PARTIAL,
        "access_notes": (
            "Flipkart Affiliate API. Requires affiliate ID + token. Rate limits "
            "unconfirmed. Request contract must be confirmed before enabling."
        ),
    },
    {
        "key": "boat",
        "display_name": "boAt",
        "domains": ["boat-lifestyle.com", "boatlifestyle.com"],
        "collector": "boat_shopify_json",
        "access_status": SourceAccessStatus.AVAILABLE,
        "access_notes": (
            "Shopify storefront exposes /products/<handle>.json publicly. No "
            "affiliate program — links are untracked."
        ),
    },
    {
        "key": "reliance_digital",
        "display_name": "Reliance Digital",
        "domains": ["reliancedigital.in"],
        "collector": "reliance_digital_http",
        "access_status": SourceAccessStatus.PARTIAL,
        "access_notes": (
            "Low robots.txt protection (research). JS rendering may be partial; "
            "structured parsing requires verified selectors — until then raw "
            "HTML is stored and structured fields remain UNKNOWN."
        ),
    },
    # ---- BLOCKED merchants: represented, never collected ----
    {
        "key": "ajio",
        "display_name": "AJIO",
        "domains": ["ajio.com", "ajiio.cc", "ajiio.in", "ajiio.co", "ajio.me", "ajio.bitiy.in"],
        "collector": None,
        "access_status": SourceAccessStatus.BLOCKED,
        "access_notes": "Akamai CDN — Access Denied. No public product API. Operator manual input only.",
    },
    {
        "key": "nykaa",
        "display_name": "Nykaa",
        "domains": ["nykaa.com"],
        "collector": None,
        "access_status": SourceAccessStatus.BLOCKED,
        "access_notes": "Akamai CDN — Access Denied. Affiliate network unknown. Manual input only.",
    },
    {
        "key": "croma",
        "display_name": "Croma",
        "domains": ["croma.com"],
        "collector": None,
        "access_status": SourceAccessStatus.BLOCKED,
        "access_notes": "Akamai CDN protection confirmed. No collection.",
    },
    {
        "key": "zepto",
        "display_name": "Zepto",
        "domains": ["zeptonow.com"],
        "collector": None,
        "access_status": SourceAccessStatus.BLOCKED,
        "access_notes": "robots.txt Disallow: / — total block. No affiliate program.",
    },
    {
        "key": "blinkit",
        "display_name": "Blinkit",
        "domains": ["blinkit.com"],
        "collector": None,
        "access_status": SourceAccessStatus.BLOCKED,
        "access_notes": "Cloudflare block confirmed. No affiliate program.",
    },
    # ---- UNKNOWN merchants: represented, access not yet determined ----
    {
        "key": "myntra",
        "display_name": "Myntra",
        "domains": ["myntra.com", "myntr.it", "myntr.in", "mynt.ro", "myntra.bitiy.in"],
        "collector": None,
        "access_status": SourceAccessStatus.UNKNOWN,
        "access_notes": "No confirmed product data API. Redirect chain resolves but no verified access.",
    },
]


def seed_merchants(session: Session) -> int:
    """Idempotently upsert the merchant registry. Returns count changed."""
    changed = 0
    for row in MERCHANT_SEED:
        m = session.scalar(select(Merchant).where(Merchant.key == row["key"]))
        if m is None:
            session.add(Merchant(**row))
            changed += 1
        else:
            # keep access verdicts authoritative (research-sourced)
            m.display_name = row["display_name"]
            m.domains = row["domains"]
            m.collector = row["collector"]
            m.access_status = row["access_status"]
            m.access_notes = row["access_notes"]
    return changed


def _url_host(url: str) -> str | None:
    """Extract the lowercased hostname from a URL (scheme optional)."""
    u = (url or "").strip()
    if "//" not in u:
        u = "//" + u  # let urlsplit treat a bare host as netloc, not path
    host = urlsplit(u).hostname
    return host.lower() if host else None


def detect_merchant_key(url: str) -> str | None:
    """Match a URL to a merchant key by hostname. Returns None if unknown.

    Matches the parsed host exactly or as a subdomain (host == dom or host
    endswith ".<dom>"), so lookalike hosts like ``myflipkart.com.evil`` no
    longer false-positive the way a raw ``dom in url`` substring test did.
    """
    host = _url_host(url)
    if not host:
        return None
    for row in MERCHANT_SEED:
        for dom in row["domains"]:
            d = dom.lower()
            if host == d or host.endswith("." + d):
                return row["key"]
    return None
