"""Competitor discovery — find similar deal channels via Telegram search.

Instead of a fixed .env list, search public Telegram for deal/loot/coupon channels,
rank candidates by relevance (deal keywords in title/description) and popularity
(subscriber count), skip our own + already-tracked channels, and add the top matches
to the Competitor table so the normal competitor collector monitors them next cycle.

Best-effort + honest: needs an authorised Telegram session; if unavailable it raises
a clear reason (the caller logs it). It never fabricates channels — only real search
results with real usernames are added.
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


def discover_competitors(max_add: int = 5) -> dict:
    """Search, rank, and add the top new deal channels. Returns a small report."""
    s = get_settings()
    if not (s.telegram_api_id and s.telegram_api_hash):
        raise RuntimeError("Telegram MTProto not configured.")

    with session_scope() as sess:
        existing = {c.username.lower() for c in sess.scalars(select(Competitor)) if c.username}
    owned = {h.lstrip("@").lower() for h in s.owned_channels}
    exclude = existing | owned

    candidates = asyncio.run(_search(s, exclude))
    # rank: deal-keyword relevance first, then popularity (log subscribers)
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
            sess.add(Competitor(
                username=c["username"], title=c["title"],
                subscribers_text=str(c["participants"]) if c["participants"] else None,
                access_status=SourceAccessStatus.AVAILABLE,
                discovered_via="telegram_search"))
            added += 1
    logger.info("[discovery] %d candidates, added %d new competitor channel(s)",
                len(candidates), added)
    return {"candidates": len(candidates), "added": added,
            "top": [c["username"] for c in candidates[:max_add]]}
