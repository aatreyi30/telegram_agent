"""Detect whether a competitor has a coupon platform website.

Flow:
  1) Check KNOWN_PLATFORMS dict (curated).
  2) HTTP-probe candidate domains derived from the title/username.
  3) Web-search via DuckDuckGo as a fallback — looks for the entity's
     own site and checks if it's a deal/coupon platform.

Returns ``"platform"`` (direct: has a coupon website), ``"channel"``
(indirect: Telegram-only deal channel), or ``None`` (inconclusive).
"""

from __future__ import annotations

import logging
import re
import warnings
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# ── known coupon platforms with a Telegram presence ──────────────────
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
    "freekaamaal": "freekaamaal.com",
    "looto": "looto.in",
    "deals4you": "deals4you.in",
    "couponz": "couponz.in",
    "dealsofindia": "dealsofindia.com",
    "couponzgurudeals": "couponzguru.com",
    "cashkarodeals": "cashkaro.com",
    "desidimedeals": "desidime.com",
}

DEAL_KEYWORDS = [
    "coupon", "deal", "offer", "cashback", "discount", "sale", "loot",
    "voucher", "promo", "savings", "bargain",
]

SOCIAL_KEYWORDS = [
    "instagram", "facebook", "twitter", "youtube", "tiktok", "linkedin",
    "wikipedia", "reddit", "quora", "medium", "blogspot", "wordpress",
    "telegram", "whatsapp", "discord",
]

TLD_CANDIDATES = [".com", ".in", ".co.in", ".org", ".net", ".info"]

# ── helpers ──────────────────────────────────────────────────────────


def _is_platform_html(html: str) -> bool:
    lower = html.lower()
    hits = sum(1 for kw in DEAL_KEYWORDS if kw in lower)
    return hits >= 2


def _http_fetch(url: str, timeout: int = 6) -> str | None:
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.read(80_000).decode("utf-8", errors="replace")
    except (HTTPError, URLError, OSError):
        return None


def _build_domain_candidates(title: str | None, username: str | None) -> list[str]:
    """Generate a diverse set of domain-name candidates from title/username.

    Keeps spaces during regex processing so that ``\\b`` word boundaries work
    correctly, then normalises to an alphanumeric slug at the end.
    """
    candidates: list[str] = []
    seen: set[str] = set()
    raw_names: list[str] = []

    if username:
        raw_names.append(username.lower().strip().lstrip("@"))
    if title:
        raw_names.append(title.lower().strip())

    def _add(slug: str, seen: set[str], cands: list[str]) -> None:
        slug = re.sub(r"[^a-z0-9]", "", slug)
        if slug and 3 <= len(slug) <= 63 and slug not in seen:
            seen.add(slug)
            cands.append(slug)

    for name in raw_names:
        # 1 — raw name as-is (alphanumeric only)
        _add(name, seen, candidates)

        # 2 — strip Telegram / channel suffixes (keeps spaces for \\b match)
        step2 = re.sub(r"\b(telegram|channel|group|official|t\.me)\b", "", name)
        _add(step2, seen, candidates)

        # 3 — strip deal-related words to expose the bare brand name
        step3 = re.sub(
            r"\b(deals?|offers?|coupons?|india|online|shopping|loot"
            r"|discounts?|sales?|promotions?|cashback)\b",
            "", step2,
        )
        _add(step3, seen, candidates)

    return candidates


def _http_probe_platform(candidates: list[str]) -> str | None:
    """Try each candidate with each TLD; return ``"platform"`` or ``"channel"``."""
    for slug in candidates:
        if len(slug) < 3:
            continue
        for tld in TLD_CANDIDATES:
            domain = f"{slug}{tld}"
            for base in (domain, f"www.{domain}"):
                for scheme in ("https", "http"):
                    url = f"{scheme}://{base}/"
                    html = _http_fetch(url)
                    if html is None:
                        continue
                    if _is_platform_html(html):
                        return "platform"
                    return "channel"  # page exists but not a deal platform
    return None


def _check_known_non_platform(name: str) -> bool:
    """Return True when the name matches a social / non-deal site."""
    return any(sk in name.lower() for sk in SOCIAL_KEYWORDS)


def _web_search_platform_detected(name: str) -> str | None:
    """Use DuckDuckGo web search as a fallback to find the competitor's website."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        logger.debug("duckduckgo_search not installed — skipping web-search fallback")
        return None

    query = f"{name} coupons deals cashback website"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))
    except Exception as exc:
        logger.debug("duckduckgo search failed for %r: %s", name, exc)
        return None

    if not results:
        return None

    # Check each result: if it's a deal platform site, return "platform"
    for r in results:
        href = (r.get("href") or "").lower().strip()
        snippet = (r.get("body") or "").lower()
        title = (r.get("title") or "").lower()

        combined = f"{title} {snippet}"
        deal_hits = sum(1 for kw in DEAL_KEYWORDS if kw in combined)
        if deal_hits < 2:
            continue

        # The link should be the platform's own domain (not a social/profile page)
        if any(sk in href for sk in SOCIAL_KEYWORDS):
            continue

        # Fetch the page and confirm
        html = _http_fetch(f"https://{href}" if not href.startswith("http") else href)
        if html and _is_platform_html(html):
            return "platform"

    return None


# ── public API ───────────────────────────────────────────────────────


def detect(title: str | None, username: str | None) -> str | None:
    """Return ``"platform"`` or ``"channel"`` for a competitor.

    ``"platform"`` = has a verifiable coupon/deal website (direct competitor).
    ``"channel"`` = Telegram-only deal channel with no website (indirect).
    Returns ``None`` when detection is inconclusive.
    """
    if not title and not username:
        return None

    name_for_check = (title or username or "").lower()

    # 1 — known platform check
    for fragment, _domain in KNOWN_PLATFORMS.items():
        if fragment in name_for_check:
            return "platform"

    # 2 — known non-platform (social media etc.)
    if _check_known_non_platform(name_for_check):
        return "channel"

    # 3 — HTTP probe domain candidates
    candidates = _build_domain_candidates(title, username)
    probe_result = _http_probe_platform(candidates)
    if probe_result is not None:
        return probe_result

    # 4 — web-search fallback
    search_name = title or username or ""
    search_result = _web_search_platform_detected(search_name)
    if search_result is not None:
        return search_result

    # 5 — if the entity is clearly a deal channel (based on name), default to "channel"
    deal_indicators = sum(1 for kw in DEAL_KEYWORDS if kw in name_for_check)
    if deal_indicators >= 2:
        return "channel"

    return None
