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
    # Additional currently-active Flipkart shortlink domains observed in the
    # extracted_links table alongside fkrt.cc/fkrt.it.
    "fkrt.co", "fkrt.site", "fkrt.to",
}

_TRACKING_PARAM_KEYS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "tag", "affid", "affExtParam1", "affExtParam2", "pid", "sub1", "sub2",
    "ref", "linkCode", "creative", "creativeASIN", "ascsubtag", "cid",
}


# --------------------------------------------------------------------------- #
# Discount %, discount band, price band, category
# --------------------------------------------------------------------------- #

# "76% OFF", "Flat 50% off" — the % figure immediately followed by an OFF cue.
# "You Save 84%" — a SAVE cue immediately before the % figure. Requiring one of
# these cues (mirroring the coupon cue-anchor rule above) avoids misreading an
# unrelated percentage (e.g. a rating, a battery level) as a discount.
_DISCOUNT_RE = re.compile(
    r"(?:(?P<off>\d{1,3})\s*%\s*off)|(?:save\s*(?P<save>\d{1,3})\s*%)",
    re.IGNORECASE,
)


def parse_discount_pct(text: str | None) -> float | None:
    """Cue-anchored discount percentage ('76% OFF', 'You Save 84%', 'Flat 50%
    off'). None when absent or when every matched value is implausible (>=100
    or <=0) — never guessed, never clamped.

    A post can carry more than one cue ("Flat 10% extra off ... 76% OFF" on a
    loot board) — the HIGHEST plausible value wins, since `.search` picking
    whichever cue happens to come first systematically under-reports the
    headline discount on multi-item boards."""
    if not text:
        return None
    best: float | None = None
    for m in _DISCOUNT_RE.finditer(text):
        raw = m.group("off") or m.group("save")
        pct = float(raw)
        if not (0 < pct < 100):
            continue
        if best is None or pct > best:
            best = pct
    return best


def discount_band(pct: float | None) -> str | None:
    """Fixed discount bands. None when pct is None (never guessed)."""
    if pct is None:
        return None
    if pct >= 70:
        return "70%+"
    if pct >= 50:
        return "50-69%"
    if pct >= 30:
        return "30-49%"
    return "<30%"


def price_band(
    prices: list[PriceMatch], threshold: float | None, is_multi_deal: bool = False,
) -> str | None:
    """Fixed price bands, derived from the stated deal price (the lowest stated
    amount — the sale price, not a crossed-out MRP) or, when no price is
    stated at all, the 'under ₹X' ceiling. None when neither is present.

    A ceiling is banded by what it *excludes*, not by its own value: "Under ₹500"
    advertises items priced below 500, so it bands as 300-499. Banding it on 500
    itself would file a budget loot board next to premium 500-999 deals and skew
    any price-band leaderboard built on this column.

    A multi-deal post (a loot board listing several unrelated items, e.g. ₹80
    and ₹2999) has no single "the deal price" — banding it on its cheapest
    item skews the leaderboard toward under-299. None rather than a guess."""
    if is_multi_deal:
        return None
    # "Under ₹500" contains a currency-anchored amount, so parse_prices reports 500 as a
    # stated price too. Drop amounts equal to the ceiling before picking the sale price,
    # or a budget board reads as a 500-999 deal. parse_prices itself stays a pure fact
    # extractor (ExtractedPrice/num_prices still record every amount in the text) —
    # only the band, the one consumer that must tell a price from a ceiling, filters.
    stated = [p.amount for p in prices if threshold is None or p.amount != threshold]
    amount = min(stated, default=None)
    if amount is None and threshold is not None:
        amount = max(threshold - 1, 0)
    if amount is None:
        return None
    if amount < 300:
        return "under-299"
    if amount < 500:
        return "300-499"
    if amount < 1000:
        return "500-999"
    if amount < 3000:
        return "1000-2999"
    return "3000+"


# Same taxonomy as enriched_deals.category (verified live values). Keyword
# lists are deterministic evidence from the post text itself — never a guess.
# Order matters only as a tie-breaker (first category with the most keyword
# hits wins); ties are rare given how specific the keyword sets are.
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "electronics-and-gadgets": [
        "earbuds", "airdopes", "earphone", "headphone", "smartwatch", "charger",
        "power bank", "powerbank", "laptop", "mobile", "smartphone", "tablet",
        "television", r"\btv\b", "speaker", "camera", "gadget", "electronics",
        "trimmer", "shaver", "router", "printer", "projector", "neckband",
        "cable", "adapter",
    ],
    "fashion-and-lifestyle": [
        "shoes", "sneakers", "footwear", "sandals", "heels", "\\btop\\b", "tops",
        "dress", "kurta", "kurti", "saree", "jeans", "t-shirt", "tshirt",
        "shirt", "jacket", "bag", "backpack", "wallet", "sunglasses",
        "\\bwatch\\b", "jewellery", "jewelry", "apparel", "clothing", "fashion",
    ],
    "beauty-and-personal-care": [
        "makeup", "lipstick", "skincare", "face wash", "shampoo", "conditioner",
        "perfume", "deodorant", "cream", "serum", "sunscreen", "cosmetic",
        "beauty", "haircare", "lotion", "moisturizer", "moisturiser",
    ],
    "home-and-living": [
        "towel", "bedsheet", "curtain", "cookware", "kitchen", "furniture",
        "decor", "mattress", "pillow", "utensil", "bottle", "home", "living",
        "storage", "organizer", "organiser", "cleaning", "robes?",
    ],
    "health-and-wellness": [
        "protein", "supplement", "vitamin", "fitness", "yoga", "\\bgym\\b",
        "wellness", "immunity", "ayurvedic",
    ],
}

_CATEGORY_RES: dict[str, re.Pattern] = {
    cat: re.compile(r"\b(?:" + "|".join(kws) + r")\b", re.IGNORECASE)
    for cat, kws in _CATEGORY_KEYWORDS.items()
}

def infer_category(text: str | None, merchant_key: str | None = None) -> str | None:
    """Deterministic keyword-table category, matching enriched_deals.category's
    taxonomy exactly. Returns None — never 'general', and never a guess from
    the merchant alone — when the text has no keyword hit, so category
    coverage stays honest and measurable rather than partly measuring merchant
    effect. ``merchant_key`` is accepted for call-site stability but carries no
    evidence on its own (AC1)."""
    best_cat, best_count = None, 0
    if text:
        for cat, rx in _CATEGORY_RES.items():
            n = len(rx.findall(text))
            if n > best_count:
                best_cat, best_count = cat, n
    return best_cat


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
