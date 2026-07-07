"""Detect whether a competitor has a coupon platform website.

Flow: 1) check known platforms dict, 2) HTTP probe their likely domain.
Returns ``"platform"``, ``"channel"``, or ``None``.
"""

from __future__ import annotations

import logging
import re
import string
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)

# Manually curated — coupon websites with a Telegram presence.
# Keyed by lowercased title-fragment or username; value is the domain.
KNOWN_PLATFORMS: dict[str, str] = {
    "grabon": "grabon.in",
    "cashkaro": "cashkaro.com",
    "coupondunia": "coupondunia.in",
    "paisawapas": "paisawapas.com",
    "couponzguru": "couponzguru.com",
    "lootdeal": "lootdeal.com",
    "lovevashikaran": "lovevashikaran.com",
    "desidime": "desidime.com",
    "bankbazaar": "bankbazaar.com",
    "paisabazaar": "paisabazaar.com",
    "couponraja": "couponraja.in",
    "couponminati": "couponminati.com",
    "deal4click": "deal4click.com",
    "techdealsindia": "techdealsindia.in",
    "smartdeals": "smartdeals.in",
    "couponmoto": "couponmoto.com",
    "indianlootdeals": "indianlootdeals.com",
    "dealshay": "dealshay.com",
}

# Words that suggest a site IS a deal/coupon platform
_DEAL_KEYWORDS = [
    "coupon", "deal", "offer", "cashback", "discount", "sale", "loot",
    "voucher", "promo", "savings", "bargain",
]

# Words that suggest a site is NOT a deal platform
_SKIP_KEYWORDS = [
    "instagram", "facebook", "twitter", "youtube", "tiktok", "linkedin",
    "wikipedia", "reddit", "quora", "medium", "blogspot", "wordpress",
    "telegram", "whatsapp", "discord",
]


def _normalize_name(name: str) -> str:
    """Turn a Telegram title/username into a domain-friendly slug."""
    slug = name.lower().strip()
    # remove common suffixes
    slug = re.sub(r"\b(telegram|channel|group|official|india|deals|coupons?)\b", "", slug)
    slug = slug.strip().replace(" ", "").replace("_", "").replace("-", "")
    # keep only ascii letters + digits
    slug = "".join(c for c in slug if c in string.ascii_lowercase + string.digits)
    return slug


def _is_platform_domain(html: str) -> bool:
    """Check if page HTML contains deal/coupon keywords."""
    lower = html.lower()
    hits = sum(1 for kw in _DEAL_KEYWORDS if kw in lower)
    return hits >= 2


def _http_probe(domain: str, timeout: int = 5) -> str | None:
    """Fetch a page and return its HTML (truncated) or None on failure."""
    for scheme in ("https", "http"):
        for base in (domain, f"www.{domain}"):
            url = f"{scheme}://{base}/"
            try:
                req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urlopen(req, timeout=timeout) as resp:
                    return resp.read(50_000).decode("utf-8", errors="replace")
            except (HTTPError, URLError, OSError):
                continue
    return None


def detect(title: str | None, username: str | None) -> str | None:
    """Return ``"platform"`` or ``"channel"`` for a competitor candidate.

    Checks known platforms first, then HTTP-probes the likely domain.
    Returns ``None`` when detection is inconclusive (e.g. network error).
    """
    if not title and not username:
        return None

    # 1 — check known platforms
    for fragment, domain in KNOWN_PLATFORMS.items():
        if (title and fragment in title.lower()) or (username and fragment in username.lower()):
            return "platform"

    # 2 — check if they're a known non-platform (social media, etc.)
    name = (title or username or "").lower()
    if any(sk in name for sk in _SKIP_KEYWORDS):
        return "channel"

    # 3 — HTTP probe
    slug = _normalize_name(title or username or "")
    if len(slug) < 4:
        return None

    for candidate_domain in (f"{slug}.com", f"{slug}.in", f"{slug}.co.in"):
        html = _http_probe(candidate_domain)
        if html is None:
            continue
        if _is_platform_domain(html):
            return "platform"
        # page exists but isn't a deal platform → channel
        return "channel"

    return None
