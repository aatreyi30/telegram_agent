"""Deterministic parsers — pure functions, no side effects, no interpretation.

Same input always yields the same output (README/09 "Normalization is
deterministic"). These extract *facts* only; they never assign business
meaning, never guess a missing value, and never define taxonomies (deal types,
CTA templates, categories) — those are learned later (RULE 3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

# --------------------------------------------------------------------------- #
# Prices
# --------------------------------------------------------------------------- #

# Currency-anchored amounts only: ₹, Rs, Rs., INR (case-insensitive), optionally
# with thousands separators and decimals. Requiring a currency marker avoids
# matching phone numbers, pin codes, quantities, etc.
# Amount = full run of digits, optionally with (Indian or western) thousands
# separators and up to 2 decimals. `\d+(?:,\d+)*` matches "1999" AND "15,304"
# AND "1,50,000"; commas are stripped before float().
_AMT = r"\d+(?:,\d+)*(?:\.\d{1,2})?"

_PRICE_RE = re.compile(
    rf"(?P<cur>₹|rs\.?|inr)\s*(?P<amt>{_AMT})",
    re.IGNORECASE,
)

# "Under ₹200", "below Rs 500", "@ ₹99" style ceilings.
_THRESHOLD_RE = re.compile(
    rf"(?:under|below|upto|up to|flat|@|at)\s*(?:₹|rs\.?|inr)\s*(?P<amt>{_AMT})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PriceMatch:
    amount: float
    currency: str
    raw_text: str
    position: int


def _to_float(num: str) -> float | None:
    try:
        return float(num.replace(",", ""))
    except ValueError:
        return None


def parse_prices(text: str | None) -> list[PriceMatch]:
    if not text:
        return []
    out: list[PriceMatch] = []
    for m in _PRICE_RE.finditer(text):
        amt = _to_float(m.group("amt"))
        if amt is None:
            continue
        out.append(
            PriceMatch(
                amount=amt,
                currency="INR",
                raw_text=m.group(0).strip(),
                position=m.start(),
            )
        )
    return out


def parse_price_threshold(text: str | None) -> float | None:
    """Explicitly stated price ceiling ("Under ₹200"). None if not stated."""
    if not text:
        return None
    m = _THRESHOLD_RE.search(text)
    if not m:
        return None
    return _to_float(m.group("amt"))


# --------------------------------------------------------------------------- #
# Coupons
# --------------------------------------------------------------------------- #

# A code token that FOLLOWS an explicit coupon/code/promo cue word. Requiring
# the cue avoids misreading random uppercase words as coupon codes. The cue is
# case-insensitive (posts capitalise "Use"/"Coupon"), but the CODE stays strictly
# uppercase-alnum so lowercase prose words are never captured as codes.
_COUPON_RE = re.compile(
    r"(?i:coupon|code|promo|voucher|use)\s*(?i:code)?\s*[:\-]?\s*([A-Z0-9]{4,15})\b"
)


def parse_coupons(text: str | None) -> list[tuple[str, str]]:
    """Return [(code, raw_match)]. Only cue-anchored codes; never guessed."""
    if not text:
        return []
    seen: dict[str, str] = {}
    for m in _COUPON_RE.finditer(text):
        code = m.group(1)
        # skip all-digit tokens (likely prices/quantities, not coupon codes)
        if code.isdigit():
            continue
        seen.setdefault(code, m.group(0).strip())
    return list(seen.items())


# --------------------------------------------------------------------------- #
# Hashtags / mentions
# --------------------------------------------------------------------------- #

_HASHTAG_RE = re.compile(r"#(\w{1,64})")
_MENTION_RE = re.compile(r"(?<!\w)@(\w{3,32})")


def parse_hashtags(text: str | None) -> list[str]:
    if not text:
        return []
    return list(dict.fromkeys(m.group(1) for m in _HASHTAG_RE.finditer(text)))


def parse_mentions(text: str | None) -> list[str]:
    if not text:
        return []
    return list(dict.fromkeys(m.group(1) for m in _MENTION_RE.finditer(text)))


# --------------------------------------------------------------------------- #
# Emoji
# --------------------------------------------------------------------------- #

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # symbols & pictographs, emoji extensions
    "\U00002600-\U000027BF"  # misc symbols + dingbats
    "\U0001F1E6-\U0001F1FF"  # regional indicators (flags)
    "\U00002190-\U000021FF"  # arrows
    "\U00002B00-\U00002BFF"  # misc symbols & arrows
    "]"
)


def parse_emojis(text: str | None) -> list[str]:
    if not text:
        return []
    return _EMOJI_RE.findall(text)


# --------------------------------------------------------------------------- #
# CTA candidates (heuristic OBSERVATION only — not a CTA taxonomy)
# --------------------------------------------------------------------------- #

# NB (RULE 3): CTA *templates* and their performance are learned later, NOT
# hardcoded. This only observes whether a post contains a CTA-shaped signal, as
# a parsing fact. The marker set is a detector, not a definition of "the CTAs".
_CTA_RE = re.compile(
    r"\b(buy now|shop now|grab (?:now|deal|it)|order now|book now|"
    r"click here|read more|get it now|buy here|shop here)\b",
    re.IGNORECASE,
)
_POINTER_RE = re.compile(r"(👉|➡️|⬇️|🔗|→)")


def detect_cta_candidates(text: str | None) -> list[str]:
    if not text:
        return []
    found = [m.group(0).strip() for m in _CTA_RE.finditer(text)]
    if _POINTER_RE.search(text) and not found:
        found.append("pointer")
    return list(dict.fromkeys(found))


# --------------------------------------------------------------------------- #
# Links
# --------------------------------------------------------------------------- #

# Domains that are URL shorteners (short path, redirects elsewhere). grbn.in is
# GrabOn's own shortener; the real merchant is unknown until resolved.
_SHORTENER_DOMAINS = {
    "grbn.in", "amzn.to", "amzn.in", "fkrt.cc", "fkrt.it", "bit.ly",
    "cutt.ly", "tinyurl.com", "t.co", "dl.flipkart.com", "myntr.it",
    "bitli.in", "wishlink.com", "ekaro.in", "inrdeals.com", "da.gd",
}

_TRACKING_PARAM_KEYS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "tag", "affid", "affExtParam1", "affExtParam2", "pid", "sub1", "sub2",
    "ref", "linkCode", "creative", "creativeASIN", "ascsubtag", "cid",
}


@dataclass(frozen=True)
class LinkInfo:
    url: str
    domain: str | None
    is_shortlink: bool
    tracking_params: dict | None


def classify_link(url: str) -> LinkInfo:
    parts = urlsplit(url)
    domain = parts.netloc.lower() or None
    is_short = domain in _SHORTENER_DOMAINS if domain else False
    params = {
        k: v[0]
        for k, v in parse_qs(parts.query).items()
        if k in _TRACKING_PARAM_KEYS
    }
    return LinkInfo(
        url=url,
        domain=domain,
        is_shortlink=is_short,
        tracking_params=params or None,
    )
