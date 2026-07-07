"""Competitor discovery — find deal channels + classify as platform or channel-only.

Telegram search finds candidates; then a web probe checks whether the entity also
has a coupon platform website. The ``category`` field is set during insert so
the dashboard can split "direct" (platform + Telegram) from "indirect" (Telegram-only).
"""

from __future__ import annotations

import asyncio
import math

from sqlalchemy import select

from src.config.settings import get_settings
from src.db.models import Competitor, SourceAccessStatus
from src.db.session import session_scope
from src.logger import get_logger

logger = get_logger(__name__)

# search queries aimed at Indian deal channels
_QUERIES = ["loot deals", "deals offers india", "coupons india",
            "online shopping deals", "amazon flipkart deals", "loot offers"]
_DEAL_TERMS = ["deal", "loot", "offer", "coupon", "discount", "sale", "cashback",
               "shopping", "price", "bazaar", "grab"]


def _relevance(title: str, about: str) -> int:
    text = f"{title} {about}".lower()
    return sum(text.count(t) for t in _DEAL_TERMS)


async def _search(settings, exclude: set[str], limit_per_query: int = 20) -> list[dict]:
    from telethon import TelegramClient
    from telethon.tl.functions.contacts import SearchRequest

    client = TelegramClient(settings.telegram_session_name,
                            settings.telegram_api_id, settings.telegram_api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session not authorised (run telegram-login).")
        found: dict[str, dict] = {}
        for q in _QUERIES:
            try:
                res = await client(SearchRequest(q=q, limit=limit_per_query))
            except Exception as e:  # per-query failure shouldn't abort discovery
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
        # enrich with the channel's "about" for better relevance where cheap
        return list(found.values())
    finally:
        await client.disconnect()


def _detect_category(title: str | None, username: str | None) -> str | None:
    """Import on demand and probe — the detector uses stdlib http.client."""
    from src.services.collection.platform_detector import detect

    try:
        return detect(title=title, username=username)
    except Exception as e:
        logger.warning("[discovery] platform detection failed for %r: %s", username or title, e)
        return None


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
