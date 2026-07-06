"""GrabOn client-specific affiliate provider (spec: GrabOn Affiliate Integration v1.0).

Activated only when ``AFFILIATE_PROVIDER=grabon``. Implements the documented
per-merchant rules and the GrabOn URL shortener, with the mandated fallback:
if shortening fails, use the generated affiliate URL so posting is never blocked.

Rules (verbatim from the spec):
  * Amazon  → https://www.amazon.in/dp/<PRODUCT_ID>/?tag=<tag>  (only the /dp/ id;
              no other query params copied).
  * Flipkart → strip everything from '?', then append the GrabOn affiliate params.
  * Shortener → POST {shortener_url} {"originalUrl": "<affiliate_url>"}; the
              shortener always receives the AFFILIATE url, never the raw merchant URL.

No GrabOn logic leaks into the core — it lives here, behind the AffiliateProvider
interface.
"""

from __future__ import annotations

import re

import httpx

from src.services.affiliate.base import AffiliateProvider, AffiliateResult
from src.logger import get_logger

logger = get_logger(__name__)

# value immediately after /dp/ (or the common /gp/product/ variant)
_AMAZON_ID_RE = re.compile(r"/(?:dp|gp/product)/([^/?#&]+)")
# short-url-ish keys a shortener response might use
_URL_KEYS = ("shortUrl", "short_url", "shortenedUrl", "shortened_url",
             "shortURL", "url", "shortLink", "link")


def _looks_like_url(v) -> bool:
    return isinstance(v, str) and v.startswith(("http://", "https://"))


def _extract_short_url(payload) -> str | None:
    """Best-effort pull of the short URL from an unknown-shaped JSON response."""
    if _looks_like_url(payload):
        return payload
    if isinstance(payload, dict):
        for k in _URL_KEYS:
            if k in payload and _looks_like_url(payload[k]):
                return payload[k]
        # nested envelopes like {"data": {...}} / {"result": {...}}
        for v in payload.values():
            found = _extract_short_url(v)
            if found:
                return found
    return None


class GrabOnAffiliateProvider(AffiliateProvider):
    name = "grabon"

    def __init__(self, settings, http_timeout: float = 10.0):
        self.shortener_url = settings.grabon_shortener_url
        self.amazon_tag = settings.grabon_amazon_tag
        self.flipkart_params = settings.grabon_flipkart_params
        # shorten EVERY link (even no-rule merchants) so output matches the channel,
        # whose links are all grbn.in. Fallback still never blocks posting.
        self.shorten_all = getattr(settings, "grabon_shorten_all", True)
        self.http_timeout = http_timeout

    # ---- merchant detection (from the URL host, when not already known) ---- #
    @staticmethod
    def _detect_merchant(url: str, merchant_key: str | None) -> str | None:
        if merchant_key:
            return merchant_key.lower()
        host = url.lower()
        if "amazon." in host:
            return "amazon"
        if "flipkart." in host:
            return "flipkart"
        return None

    # ---- pure URL builders (no network — unit tested directly) ---- #
    def _amazon_affiliate_url(self, url: str) -> tuple[str | None, list[str]]:
        m = _AMAZON_ID_RE.search(url)
        if not m:
            return None, ["Amazon URL has no /dp/<id> — cannot build affiliate link; using clean URL."]
        product_id = m.group(1)
        return f"https://www.amazon.in/dp/{product_id}/?tag={self.amazon_tag}", []

    def _flipkart_affiliate_url(self, url: str) -> tuple[str | None, list[str]]:
        base = url.split("?", 1)[0]
        if "/p/" not in base:
            return None, ["Flipkart URL missing product path (/p/) — using clean URL."]
        return f"{base}?{self.flipkart_params}", []

    def build_affiliate_url(self, url: str, merchant: str | None) -> tuple[str | None, list[str]]:
        if merchant == "amazon":
            return self._amazon_affiliate_url(url)
        if merchant == "flipkart":
            return self._flipkart_affiliate_url(url)
        return None, [f"No GrabOn affiliate rule for merchant '{merchant or 'unknown'}' — using clean URL."]

    # ---- shortener (network; falls back gracefully) ---- #
    def shorten(self, affiliate_url: str) -> tuple[str | None, list[str]]:
        try:
            resp = httpx.post(self.shortener_url, json={"originalUrl": affiliate_url},
                              headers={"Content-Type": "application/json"},
                              timeout=self.http_timeout)
            resp.raise_for_status()
            try:
                payload = resp.json()
            except ValueError:
                payload = resp.text.strip()
            short = _extract_short_url(payload)
            if short:
                return short, []
            return None, ["Shortener responded but no short URL found in the payload — "
                          "falling back to the affiliate URL."]
        except Exception as e:  # network / non-2xx / timeout — never block posting
            logger.warning("[affiliate:grabon] shortener failed: %s", e)
            return None, [f"Shortener call failed ({type(e).__name__}) — falling back to the "
                          "affiliate URL."]

    # ---- interface ---- #
    def generate(self, product_url: str, merchant_key: str | None = None) -> AffiliateResult:
        merchant = self._detect_merchant(product_url, merchant_key)
        affiliate_url, notes = self.build_affiliate_url(product_url, merchant)

        # what the shortener receives: the affiliate URL when we have a rule, else the clean
        # product URL when shorten_all is on (so every posted link is a grbn.in link).
        to_shorten = affiliate_url or (product_url if self.shorten_all else None)
        short_url = None
        if to_shorten:
            short_url, snotes = self.shorten(to_shorten)
            notes += snotes
            if not affiliate_url and short_url:
                notes.append("No affiliate rule for this merchant; branded short link only "
                             "(no affiliate params).")

        return AffiliateResult(
            original_url=product_url,
            merchant_key=merchant,
            affiliate_url=affiliate_url,
            short_url=short_url,
            provider=self.name,
            shortened=bool(short_url),
            notes=notes,
        )
