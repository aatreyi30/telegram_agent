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
    from telethon.errors import FloodWaitError
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
            except FloodWaitError as e:
                logger.warning("[discovery] query %r flood-wait %ss — aborting search", q, e.seconds)
                return list(found.values())
            except Exception as e:
                logger.warning("[discovery] query %r failed: %s", q, e)
                continue
            await asyncio.sleep(1.5)
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
    from telethon.errors import FloodWaitError
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
            except FloodWaitError as e:
                logger.warning("[discovery:resolve] query %r flood-wait %ss — aborting search", q, e.seconds)
                return list(found.values())
            except Exception as e:
                logger.debug("[discovery:resolve] query %r failed: %s", q, e)
                continue
            await asyncio.sleep(1.5)
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
    newly_added_usernames = []
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
                last_collected_at=None,  # Never collected yet
            ))
            newly_added_usernames.append(c["username"])
            added += 1
    logger.info("[discovery] %d candidates, +%d new", len(candidates), added)
    
    # Trigger initial backfill for newly discovered competitors
    if newly_added_usernames:
        logger.info("[discovery] triggering initial backfill for %d new competitors", len(newly_added_usernames))
        from src.services.collection.telegram_competitor import CompetitorCollector
        from src.services.collection.base import JobRunner
        from src.db.models import CollectionType
        runner = JobRunner()
        for username in newly_added_usernames:
            try:
                job = runner.run_collector(
                    CompetitorCollector(username, max_pages=5, initial_backfill=True),
                    collection_type=CollectionType.MANUAL,
                    target=f"backfill_{username}"
                )
                logger.info("[discovery] backfill completed for %s: added=%d", username, job.records_added)
            except Exception as e:
                logger.error("[discovery] backfill failed for %s: %s", username, e)
    
    return {"candidates": len(candidates), "added": added,
            "top": [c["username"] for c in candidates[:max_add]]}


def verify_candidate(brand: str, candidates: list[dict]) -> tuple[str | None, float, str]:
    """Resolve the official channel for ``brand`` from candidate dicts.

    Candidates are the raw dicts produced by ``_search_name_variations``/``_search``
    (``username``, ``title``, ``participants``, optionally ``score``). Similarity and
    relevance are computed here from ``title`` via the existing heuristics
    (``_name_similarity_score`` / ``_relevance``) unless a caller already supplied
    ``similarity``/``relevance``/``description`` on the dict.

    Returns ``(username_or_none, confidence 0..1, method)`` where
    ``method`` is ``"heuristic"`` or ``"ai"``. Deterministic gate first; the AI
    verifier is only consulted for ambiguous cases, and a weak sole/lead candidate
    is rejected outright rather than blindly trusted (the accuracy bug this fixes:
    discovery used to store the top-ranked candidate even when it barely matched).
    """
    if not candidates:
        return None, 0.0, "heuristic"

    scored = []
    for c in candidates:
        title = c.get("title") or c.get("username") or ""
        sim = c.get("similarity")
        if sim is None:
            sim = _name_similarity_score(brand, title)
        rel = c.get("relevance")
        if rel is None:
            rel = _relevance(title, c.get("description") or "")
        scored.append((float(sim), rel, c))

    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    sim, rel, top = scored[0]
    runner_sim = scored[1][0] if len(scored) > 1 else None

    # Strong deterministic accept.
    if sim >= 0.8 and rel >= 2:
        return top["username"], round(min(0.99, sim), 2), "heuristic"
    # Clearly weak sole/lead candidate -> reject rather than blindly trust.
    if sim < 0.3 and rel < 2:
        return None, round(sim, 2), "heuristic"

    # Ambiguous -> ask the LLM for a structured verdict (best-effort).
    from src.ai.client import AIClient, AIUnavailable
    from src.ai.prompts import VERIFY_CANDIDATE_SYSTEM, verify_candidate_input

    ai = AIClient()
    ok, _ = ai.available()
    if ok:
        try:
            lines = "\n".join(
                f"- @{c.get('username')}: title={c.get('title', '')!r}"
                for _, _, c in scored[:6]
            )
            raw = ai.complete(
                verify_candidate_input(brand, lines),
                system_extra=VERIFY_CANDIDATE_SYSTEM,
                max_tokens=120,
            )
            import json
            import re

            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                data = json.loads(m.group(0))
                uname = data.get("username")
                conf = float(data.get("confidence", 0.0))
                if uname:
                    match = next(
                        (c for _, _, c in scored
                         if c.get("username", "").lstrip("@").lower() == str(uname).lstrip("@").lower()),
                        None,
                    )
                    if match is not None:
                        return match["username"], round(conf, 2), "ai"
                return None, round(conf, 2), "ai"
        except (AIUnavailable, Exception) as e:
            logger.debug("[discovery:verify] AI verification failed for %r: %s", brand, e)

    # AI unavailable/failed: accept the lead only if it clearly beats the runner-up.
    if sim >= 0.6 and (runner_sim is None or sim - runner_sim >= 0.2):
        return top["username"], round(sim, 2), "heuristic"
    return None, round(sim, 2), "heuristic"


def resolve_username(name: str) -> dict | None:
    """Given a raw competitor name, search Telegram for the best-matching channel.

    Handles name variations (abbreviations, suffixes, prefixes, etc.), then runs
    the result through ``verify_candidate`` (stricter deterministic gate + AI
    verifier for ambiguous cases) instead of blindly trusting the top-ranked hit.
    Returns dict with ``username``, ``title``, ``participants``, ``score``,
    ``resolution_confidence``, ``verified_by``, or ``None`` if nothing confident
    enough was found. When a ``Competitor`` row already exists for ``name``, its
    ``resolution_confidence``/``verified_by`` columns are updated with the verdict.
    """
    s = get_settings()
    if not (s.telegram_api_id and s.telegram_api_hash):
        logger.warning("[discovery:resolve] Telegram MTProto not configured.")
        return None

    # Category-gated search order (product requirement): a competitor already
    # classified "channel" (indirect, Telegram-only) skips the web-search step
    # entirely and goes straight to Telegram search. A competitor already
    # classified "platform" (direct) — or not yet classified — gets a web search
    # first (via the same platform_detector pipeline used everywhere else in this
    # codebase to set the category field: known-platform list, HTTP domain probe,
    # then DuckDuckGo search), then the Telegram search below. Telegram search
    # always runs regardless of category — every competitor still needs a
    # resolved Telegram handle to be collected.
    with session_scope() as sess:
        existing_comp = next(
            (c for c in sess.scalars(select(Competitor))
             if c.username and c.username.lower() == name.lower()),
            None,
        )
    known_category = existing_comp.category if existing_comp else None

    if known_category == "channel":
        category_hint = "channel"
        logger.info(
            "[discovery:resolve] %r already classified 'channel' (indirect) — "
            "skipping web search, going straight to Telegram search", name,
        )
    else:
        category_hint = _detect_category(name, name)
        logger.info(
            "[discovery:resolve] web search for %r (was %r) -> category_hint=%r, "
            "now running Telegram search", name, known_category, category_hint,
        )

    with session_scope() as sess:
        existing = {c.username.lower() for c in sess.scalars(select(Competitor)) if c.username}
    from src.services.collection.channels import owned_handles
    owned = {h.lstrip("@").lower() for h in owned_handles()}
    exclude = existing | owned

    candidates = asyncio.run(_search_name_variations(s, name, exclude))
    if not candidates:
        logger.info("[discovery:resolve] no Telegram channels found for %r", name)
        return None

    # score each for logging/back-compat: name similarity + relevance + log(participants)
    for c in candidates:
        sim = _name_similarity_score(name, c["title"])
        rel = _relevance(c["title"], "")
        c["score"] = sim * 10 + rel + math.log10(max(c["participants"], 1))
    candidates.sort(key=lambda c: c["score"], reverse=True)

    username, confidence, method = verify_candidate(name, candidates)
    if username is None:
        logger.info(
            "[discovery:resolve] no confident match for %r among %d candidates "
            "(best confidence=%.2f) — skipping",
            name, len(candidates), confidence,
        )
        return None

    best = next(c for c in candidates if c["username"] == username)
    logger.info(
        "[discovery:resolve] %r -> %r (title=%r, confidence=%.2f via %s)",
        name, best["username"], best["title"], confidence, method,
    )

    # Persist resolution provenance on the existing Competitor row for this name, if any.
    # category_hint (from the web-search step above, or the pre-existing 'channel'
    # classification that made us skip it) is only written when the row doesn't
    # already carry a category, so a confirmed classification is never overwritten
    # by a later, possibly weaker, hint.
    with session_scope() as sess:
        comp = next(
            (c for c in sess.scalars(select(Competitor)) if c.username and c.username.lower() == name.lower()),
            None,
        )
        if comp is not None:
            comp.resolution_confidence = confidence
            comp.verified_by = method
            if category_hint and not comp.category:
                comp.category = category_hint

    best["resolution_confidence"] = confidence
    best["verified_by"] = method
    best["category_hint"] = category_hint
    return best