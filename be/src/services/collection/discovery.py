"""Competitor discovery — find deal channels on Telegram & classify.

Two modes:

* **Generic discovery** — searches Telegram for deal channels using
  broad queries, ranks by relevance + subscribers, classifies, stores.
* **Name resolution** — given a competitor name (e.g. ``"desidime"``),
  searches Telegram for channels matching that name or its variations
  (abbreviations, suffixes like "deals", "offers", "india", etc.) and
  returns the best-matching username.

The ``category`` field distinguishes "direct" (platform + Telegram, i.e.
the entity also has a coupon website) from "indirect" (Telegram-only).
"""

from __future__ import annotations

import asyncio
import math
import re

from sqlalchemy import select

from src.config.settings import get_settings
from src.db.models import Competitor, SourceAccessStatus
from src.db.session import session_scope
from src.logger import get_logger

logger = get_logger(__name__)

# ── Telegram search queries (generic discovery) ─────────────────────
_QUERIES = [
    "loot deals", "deals offers india", "coupons india",
    "online shopping deals", "amazon flipkart deals", "loot offers",
]

_DEAL_TERMS = [
    "deal", "loot", "offer", "coupon", "discount", "sale", "cashback",
    "shopping", "price", "bazaar", "grab",
]

# Suffixes / prefixes to append when searching for a specific name
_NAME_VARIATIONS = [
    "deals", "offers", "coupons", "india", "loot", "shopping",
    "promotions", "cashback", "discounts", "online",
    "daily", "bazaar", "club", "zone", "hub", "world",
]
# Common abbreviations / short forms (these will be tried alone and combined)
_ABBREVIATIONS = {
    "offers": "off", "discounts": "dis", "promotions": "promo",
    "shopping": "shop", "cashback": "cb", "coupons": "cpn",
}


def _relevance(title: str, about: str) -> int:
    text = f"{title} {about}".lower()
    return sum(text.count(t) for t in _DEAL_TERMS)


def _name_similarity_score(query: str, title: str) -> float:
    """Score how well a Telegram channel title matches a query name.

    Handles exact matches, containment, common prefixes, and
    character-level overlap. Returns 0.0 – 1.0.
    """
    q = re.sub(r"[^a-z0-9]", "", query.lower())
    t = re.sub(r"[^a-z0-9]", "", title.lower())

    if not q or not t:
        return 0.0

    # exact match
    if q == t:
        return 1.0

    # query is contained in title (e.g. "desidime" in "desidimedeals")
    if q in t:
        return 0.9

    # title is contained in query
    if t in q:
        return 0.8

    # one-sided overlap: most chars of the shorter string appear in the longer
    shorter, longer = (q, t) if len(q) <= len(t) else (t, q)
    common = sum(1 for ch in shorter if ch in longer)
    overlap = common / len(longer)
    if overlap >= 0.7:
        return overlap

    # common prefix overlap
    min_len = min(len(q), len(t))
    if min_len >= 3:
        match = 0
        for i in range(min_len):
            if q[i] == t[i]:
                match += 1
            else:
                break
        prefix_ratio = match / max(len(q), len(t))
        if prefix_ratio >= 0.4:
            return prefix_ratio

    return 0.0


def _generate_search_variations(name: str) -> list[str]:
    """Generate search queries for a given competitor name.

    Tries: raw name, with common suffixes/prefixes, abbreviations,
    underscores, and telegram-style handle variants.
    """
    base = re.sub(r"[^a-z0-9]", "", name.lower().strip())
    if not base:
        return []

    variations = [base]

    # suffixes
    for suffix in _NAME_VARIATIONS:
        variations.append(f"{base} {suffix}")
        variations.append(f"{base}{suffix}")

    # abbreviated suffixes
    for full, short in _ABBREVIATIONS.items():
        if full in base:
            alt = base.replace(full, short)
            if alt != base:
                variations.append(alt)
        variations.append(f"{base} {short}")

    # prefixes
    for prefix in ("the", "official", "real", "best"):
        variations.append(f"{prefix} {base}")
        variations.append(f"{prefix}{base}")

    # underscore / dot variants
    for sep in ("_", "."):
        variations.append(f"{base}{sep}official")
        variations.append(f"{base}{sep}india")
        variations.append(f"{base}{sep}deals")

    # remove common deal keywords to get bare brand
    bare = re.sub(
        r"\b(deals?|offers?|coupons?|india|online|shopping|loot"
        r"|discounts?|sales?|promotions?|cashback)\b",
        "", base,
    ).strip()
    if bare and bare != base:
        variations.append(bare)

    return variations


def _normalise_username(name: str) -> str:
    """Remove @ prefix if present."""
    return name.lstrip("@").strip()


# ── Telegram search (async) ─────────────────────────────────────────


async def _search(settings, exclude: set[str], limit_per_query: int = 20) -> list[dict]:
    from telethon import TelegramClient
    from telethon.tl.functions.contacts import SearchRequest

    client = TelegramClient(
        settings.telegram_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session not authorised (run telegram-login).")
        found: dict[str, dict] = {}
        for q in _QUERIES:
            try:
                res = await client(SearchRequest(q=q, limit=limit_per_query))
            except Exception as e:
                logger.warning("[discovery] query %r failed: %s", q, e)
                continue
            for chat in getattr(res, "chats", []):
                uname = getattr(chat, "username", None)
                is_channel = getattr(chat, "broadcast", False)
                if not uname or not is_channel:
                    continue
                key = uname.lower()
                if key in exclude or key in found:
                    continue
                found[key] = {
                    "username": uname,
                    "title": getattr(chat, "title", None) or uname,
                    "participants": getattr(chat, "participants_count", None) or 0,
                }
        return list(found.values())
    finally:
        await client.disconnect()


async def _search_name_variations(
    settings, name: str, exclude: set[str], limit_per_query: int = 10,
) -> list[dict]:
    """Search Telegram for a specific name and all its variations."""
    from telethon import TelegramClient
    from telethon.tl.functions.contacts import SearchRequest

    client = TelegramClient(
        settings.telegram_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session not authorised.")
        found: dict[str, dict] = {}
        queries = _generate_search_variations(name)
        for q in queries:
            try:
                res = await client(SearchRequest(q=q, limit=limit_per_query))
            except Exception as e:
                logger.debug("[discovery:resolve] query %r failed: %s", q, e)
                continue
            for chat in getattr(res, "chats", []):
                uname = _normalise_username(getattr(chat, "username", None) or "")
                is_channel = getattr(chat, "broadcast", False)
                if not uname or not is_channel:
                    continue
                key = uname.lower()
                if key in exclude or key in found:
                    continue
                found[key] = {
                    "username": uname,
                    "title": getattr(chat, "title", None) or uname,
                    "participants": getattr(chat, "participants_count", None) or 0,
                }
        return list(found.values())
    finally:
        await client.disconnect()


def _detect_category(title: str | None, username: str | None) -> str | None:
    from src.services.collection.platform_detector import detect

    try:
        return detect(title=title, username=username)
    except Exception as e:
        logger.warning("[discovery] platform detection failed for %r: %s", username or title, e)
        return None


# ── public API ───────────────────────────────────────────────────────


def discover_competitors(max_add: int = 5) -> dict:
    """Search, rank, classify, and add the top new competitor channels."""
    s = get_settings()
    if not (s.telegram_api_id and s.telegram_api_hash):
        raise RuntimeError("Telegram MTProto not configured.")

    with session_scope() as sess:
        existing = {c.username.lower() for c in sess.scalars(select(Competitor)) if c.username}
    from src.services.collection.channels import owned_handles
    owned = {h.lstrip("@").lower() for h in owned_handles()}
    exclude = existing | owned

    candidates = asyncio.run(_search(s, exclude))
    for c in candidates:
        c["score"] = _relevance(c["title"], "") + math.log10(max(c["participants"], 1))
    candidates.sort(key=lambda c: c["score"], reverse=True)

    added = 0
    with session_scope() as sess:
        for c in candidates:
            if added >= max_add:
                break
            if sess.scalar(select(Competitor).where(Competitor.username == c["username"])):
                continue
            category = _detect_category(c.get("title"), c["username"])
            sess.add(Competitor(
                username=c["username"], title=c["title"],
                subscribers_text=str(c["participants"]) if c["participants"] else None,
                access_status=SourceAccessStatus.AVAILABLE,
                discovered_via="telegram_search",
                category=category,
            ))
            added += 1
    logger.info("[discovery] %d candidates, +%d new", len(candidates), added)
    return {"candidates": len(candidates), "added": added,
            "top": [c["username"] for c in candidates[:max_add]]}


def resolve_username(name: str) -> dict | None:
    """Given a raw competitor name, search Telegram for the best-matching channel.

    Handles name variations (abbreviations, suffixes, prefixes, etc.).
    Returns dict with ``username``, ``title``, ``participants``, ``score``
    or ``None`` if nothing reasonable found.
    """
    s = get_settings()
    if not (s.telegram_api_id and s.telegram_api_hash):
        logger.warning("[discovery:resolve] Telegram MTProto not configured.")
        return None

    with session_scope() as sess:
        existing = {c.username.lower() for c in sess.scalars(select(Competitor)) if c.username}
    from src.services.collection.channels import owned_handles
    owned = {h.lstrip("@").lower() for h in owned_handles()}
    exclude = existing | owned

    candidates = asyncio.run(_search_name_variations(s, name, exclude))
    if not candidates:
        logger.info("[discovery:resolve] no Telegram channels found for %r", name)
        return None

    # score each: name similarity + relevance + log(participants)
    for c in candidates:
        sim = _name_similarity_score(name, c["title"])
        rel = _relevance(c["title"], "")
        c["score"] = sim * 10 + rel + math.log10(max(c["participants"], 1))

    candidates.sort(key=lambda c: c["score"], reverse=True)
    best = candidates[0]

    # only return if we have a reasonable match
    sim = _name_similarity_score(name, best["title"])
    if sim < 0.3 and _relevance(best["title"], "") < 2:
        logger.info(
            "[discovery:resolve] best match for %r is %r (title=%r, sim=%.2f) — too weak, skipping",
            name, best["username"], best["title"], sim,
        )
        return None

    logger.info(
        "[discovery:resolve] %r -> %r (title=%r, sim=%.2f)",
        name, best["username"], best["title"], sim,
    )
    return best
