"""Competitor collector — public channels via Telethon (primary) or t.me/s (fallback).

Primary: Telethon MTProto — rich data (views, forwards, reactions).
Fallback: t.me/s web preview — text-only with approximate views.

When the configured username is not found, ``resolve_username()`` searches
Telegram for the name and its common variations (abbreviations, suffixes,
prefixes, etc.) and caches the correct handle in-process.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from src.services.collection.base import BaseCollector, CollectorResult
from src.services.collection.discovery import resolve_username, _detect_category
from src.services.collection.raw_store import store_raw
from src.services.collection.util import content_hash, extract_urls, parse_abbreviated_int, to_utc
from src.config.settings import get_settings
from src.db.models import Competitor, CompetitorPost, SourceAccessStatus
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus
from src.logger import get_logger

logger = get_logger(__name__)

BASE_URL = "https://t.me/s/{username}"

# In-process cache: original_configured_name -> resolved_actual_handle
_resolved_handle: dict[str, str] = {}

# Max messages to fetch per Telethon run (increased for better coverage)
_TELETHON_LIMIT = 200


class CompetitorCollector(BaseCollector):
    name = "telegram_competitor"

    def __init__(self, username: str, max_pages: int = 1, initial_backfill: bool = False):
        self.original_name = username.lstrip("@")
        self.username = _resolved_handle.get(self.original_name, self.original_name)
        self.max_pages = max_pages
        self.initial_backfill = initial_backfill  # If True, fetch full month of data
        self.settings = get_settings()
        self.bus = get_event_bus()

    # ── entry point ───────────────────────────────────────────────── #
    def run(self, job) -> CollectorResult:
        comp_id = self._ensure_competitor()

        # 1 — Try Telethon (Telegram API) for rich data
        telethon_result = asyncio.run(self._run_telethon(comp_id, job.id))
        if telethon_result is not None:
            self._touch_timestamp(comp_id)
            self._emit(EventType.COMPETITOR_UPDATED, "competitor", comp_id, job.id,
                       {"posts_seen": telethon_result.processed, "source": "telethon"})
            return telethon_result

        # 2 — Fall back to t.me/s scraping
        httpx_result = self._run_httpx(comp_id, job)
        if httpx_result.processed > 0 or not httpx_result.skipped_reason:
            self._touch_timestamp(comp_id)
            self._emit(EventType.COMPETITOR_UPDATED, "competitor", comp_id, job.id,
                       {"posts_seen": httpx_result.processed, "source": "tme_s"})
        return httpx_result

    # ── Telethon (primary) ────────────────────────────────────────── #
    async def _run_telethon(self, comp_id: int, job_id: int) -> CollectorResult | None:
        from telethon import TelegramClient
        from telethon.errors import UsernameNotOccupiedError, FloodWaitError

        if not (self.settings.telegram_api_id and self.settings.telegram_api_hash):
            return None

        client = TelegramClient(
            self.settings.telegram_session_name,
            self.settings.telegram_api_id,
            self.settings.telegram_api_hash,
        )
        await client.connect()
        try:
            if not await client.is_user_authorized():
                logger.debug("[competitor:telethon] session not authorised — skipping Telethon")
                return None

            entity = await self._resolve_get_entity(client)
            if entity is None:
                return None

            result = CollectorResult()
            # For initial backfill, fetch more messages (approx 1 month worth)
            limit = _TELETHON_LIMIT * 10 if self.initial_backfill else _TELETHON_LIMIT
            logger.info("[competitor:telethon] fetching with limit=%d (initial_backfill=%s)", limit, self.initial_backfill)
            async for msg in client.iter_messages(entity, limit=limit):
                if msg.message is None and not msg.media:
                    continue
                added, updated = await self._store_telethon_post(comp_id, msg, job_id)
                result.processed += 1
                result.added += added
                result.updated += updated

            # Mark competitor as available and update metadata.
            # _update_from_entity manages its own session_scope; call it directly —
            # run_in_executor returns a Future, which is not an async context manager.
            self._update_from_entity(comp_id, entity)

            return result

        except FloodWaitError as exc:
            logger.warning("[competitor:telethon] flood-wait %ss for %r; not a Telethon failure",
                           getattr(exc, "seconds", "?"), self.username)
            raise  # let the caller back off; do NOT fall through to the degraded t.me/s scrape
        except Exception as exc:
            logger.debug("[competitor:telethon] error for %r: %s", self.username, exc)
            return None
        finally:
            await client.disconnect()

    async def _resolve_get_entity(self, client):
        """Try to get the Telegram entity for ``self.username``.

        If the direct lookup fails, attempt name-variation resolution
        via ``resolve_username()`` and cache the result.
        """
        from telethon.errors import UsernameNotOccupiedError

        # 1 — direct lookup
        try:
            return await client.get_entity(self.username)
        except (UsernameNotOccupiedError, ValueError, TypeError):
            pass
        except Exception as exc:
            logger.debug("[competitor:resolve] get_entity failed for %r: %s", self.username, exc)
            return None

        # 2 — name-variation resolution
        if self.username.lower() == self.original_name.lower():
            resolved = resolve_username(self.original_name)
            if resolved is None:
                logger.info("[competitor:resolve] no match found for %r", self.original_name)
                return None
            new_handle = resolved["username"].lower()
            _resolved_handle[self.original_name] = new_handle
            self.username = new_handle
            logger.info("[competitor:resolve] %r -> %r", self.original_name, new_handle)

            try:
                return await client.get_entity(self.username)
            except (UsernameNotOccupiedError, ValueError, TypeError):
                return None
            except Exception as exc:
                logger.debug("[competitor:resolve] get_entity of resolved handle %r failed: %s",
                             self.username, exc)
                return None

        # 3 — already have a resolved handle but it didn't work; try original
        logger.info("[competitor:resolve] cached handle %r failed, trying original %r",
                    self.username, self.original_name)
        try:
            entity = await client.get_entity(self.original_name)
            _resolved_handle.pop(self.original_name, None)
            self.username = self.original_name
            return entity
        except Exception:
            return None

    async def _store_telethon_post(self, comp_id: int, msg, job_id: int) -> tuple[int, int]:
        text = msg.message or None
        links = extract_urls(text)
        digest = content_hash(text, links)
        reactions_total = self._sum_reactions(msg)
        added = updated = 0

        with session_scope() as s:
            existing = s.scalar(
                select(CompetitorPost).where(
                    CompetitorPost.competitor_id == comp_id,
                    CompetitorPost.tg_message_id == msg.id,
                )
            )
            now = datetime.now(timezone.utc)
            if existing is None:
                cp = CompetitorPost(
                    competitor_id=comp_id,
                    tg_message_id=msg.id,
                    posted_at=to_utc(getattr(msg, "date", None)),
                    text=text,
                    content_sha256=digest,
                    links=links or None,
                    has_media=bool(msg.media),
                    views=getattr(msg, "views", None),
                    forwards=getattr(msg, "forwards", None),
                    reactions_total=reactions_total,
                    collected_at=now,
                )
                s.add(cp)
                s.flush()
                added = 1
                logger.info("[competitor:collector] post saved: competitor_id=%d post_id=%d tg_message_id=%d", comp_id, cp.id, msg.id)
            else:
                changed = existing.content_sha256 != digest
                existing.views = getattr(msg, "views", None)
                existing.forwards = getattr(msg, "forwards", None)
                existing.reactions_total = reactions_total
                if changed:
                    existing.text = text
                    existing.content_sha256 = digest
                    existing.links = links or None
                    updated = 1
        return added, updated

    @staticmethod
    def _sum_reactions(msg) -> int | None:
        reactions = getattr(msg, "reactions", None)
        if not reactions or not getattr(reactions, "results", None):
            return None
        return sum(getattr(r, "count", 0) for r in reactions.results)

    def _update_from_entity(self, comp_id: int, entity) -> None:
        with session_scope() as s:
            comp = s.get(Competitor, comp_id)
            comp.access_status = SourceAccessStatus.AVAILABLE
            comp.title = getattr(entity, "title", None) or comp.title
            comp.category = _detect_category(
                getattr(entity, "title", None), self.username
            ) or comp.category

    # ── t.me/s fallback ───────────────────────────────────────────── #
    def _run_httpx(self, comp_id: int, job) -> CollectorResult:
        result = CollectorResult()
        before: int | None = None
        pages_done = 0
        # For initial backfill, fetch more pages (approx 1 month worth)
        max_pages = self.max_pages * 10 if self.initial_backfill else self.max_pages
        logger.info("[competitor:httpx] fetching with max_pages=%d (initial_backfill=%s)", max_pages, self.initial_backfill)

        with httpx.Client(
            headers={"User-Agent": self.settings.tme_user_agent},
            timeout=30.0,
            follow_redirects=True,
        ) as client:
            while pages_done < max_pages:
                url = BASE_URL.format(username=self.username)
                params = {"before": before} if before else None
                resp = client.get(url, params=params)

                if resp.status_code == 404:
                    resolved = self._try_resolve(comp_id)
                    if resolved:
                        before = None
                        pages_done = 0
                        continue
                    result.skipped_reason = "channel not accessible via t.me/s (404)"
                    return result
                resp.raise_for_status()

                if "/s/" not in str(resp.url):
                    resolved = self._try_resolve(comp_id)
                    if resolved:
                        before = None
                        pages_done = 0
                        continue
                    result.skipped_reason = (
                        f"'{self.username}' has no public t.me/s preview "
                        "(not a public channel, or wrong username)."
                    )
                    return result

                html = resp.text
                with session_scope() as s:
                    store_raw(
                        s, source=self.name,
                        source_ref=f"{self.username}:before={before or ''}",
                        payload=html, job_id=job.id, content_type="text/html",
                    )

                self._update_channel_meta(comp_id, html)
                posts = self._parse_posts(html)
                if not posts:
                    break

                oldest_id = None
                for p in posts:
                    added, updated = self._store_httpx_post(comp_id, p, job.id)
                    result.processed += 1
                    result.added += added
                    result.updated += updated
                    oldest_id = p["msg_id"] if oldest_id is None else min(oldest_id, p["msg_id"])

                pages_done += 1
                before = oldest_id
                if before is None:
                    break
                time.sleep(self.settings.tme_request_delay_seconds)

        return result

    def _parse_posts(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        out: list[dict] = []
        for node in soup.select(".tgme_widget_message"):
            data_post = node.get("data-post")
            if not data_post or "/" not in data_post:
                continue
            try:
                msg_id = int(data_post.split("/")[-1])
            except ValueError:
                continue

            text_node = node.select_one(".tgme_widget_message_text")
            text = text_node.get_text(separator="\n", strip=True) if text_node else None

            views_node = node.select_one(".tgme_widget_message_views")
            views_text = views_node.get_text(strip=True) if views_node else None

            time_node = node.select_one(".tgme_widget_message_date time")
            posted_at = None
            if time_node:
                dt_attr = time_node.get("datetime")
                if dt_attr:
                    try:
                        posted_at = datetime.fromisoformat(dt_attr.replace("Z", "+00:00"))
                    except ValueError:
                        posted_at = None

            links = extract_urls(text)
            if text_node:
                for a in text_node.select("a"):
                    href = a.get("href")
                    if href and href.startswith("http") and href not in links:
                        links.append(href)

            has_media = bool(
                node.select_one(".tgme_widget_message_photo_wrap")
                or node.select_one(".tgme_widget_message_video")
                or node.select_one(".tgme_widget_message_document")
            )

            out.append({
                "msg_id": msg_id,
                "text": text,
                "views_text": views_text,
                "posted_at": to_utc(posted_at),
                "links": links,
                "has_media": has_media,
            })
        return out

    def _store_httpx_post(self, comp_id: int, p: dict, job_id: int) -> tuple[int, int]:
        digest = content_hash(p["text"], p["links"])
        added = updated = 0
        with session_scope() as s:
            existing = s.scalar(
                select(CompetitorPost).where(
                    CompetitorPost.competitor_id == comp_id,
                    CompetitorPost.tg_message_id == p["msg_id"],
                )
            )
            now = datetime.now(timezone.utc)
            views_int = parse_abbreviated_int(p["views_text"])
            if existing is None:
                cp = CompetitorPost(
                    competitor_id=comp_id,
                    tg_message_id=p["msg_id"],
                    posted_at=p["posted_at"],
                    text=p["text"],
                    content_sha256=digest,
                    links=p["links"] or None,
                    has_media=p["has_media"],
                    views_text=p["views_text"],
                    views=views_int,
                    forwards=None,
                    collected_at=now,
                )
                s.add(cp)
                s.flush()
                added = 1
                logger.info("[competitor:collector] post saved: competitor_id=%d post_id=%d tg_message_id=%d", comp_id, cp.id, p["msg_id"])
            else:
                changed = existing.content_sha256 != digest
                existing.views_text = p["views_text"]
                existing.views = views_int
                if changed:
                    existing.text = p["text"]
                    existing.content_sha256 = digest
                    existing.links = p["links"] or None
                    updated = 1
        return added, updated

    def _update_channel_meta(self, comp_id: int, html: str) -> None:
        soup = BeautifulSoup(html, "html.parser")
        title_node = soup.select_one(".tgme_channel_info_header_title")
        desc_node = soup.select_one(".tgme_channel_info_description")
        subs = None
        for counter in soup.select(".tgme_channel_info_counter"):
            label = counter.select_one(".counter_type")
            value = counter.select_one(".counter_value")
            if label and value and "subscriber" in label.get_text(strip=True).lower():
                subs = value.get_text(strip=True)
        with session_scope() as s:
            comp = s.get(Competitor, comp_id)
            if title_node:
                comp.title = title_node.get_text(strip=True)
            if desc_node:
                comp.description = desc_node.get_text(separator="\n", strip=True)
            if subs:
                comp.subscribers_text = subs

    # ── shared helpers ────────────────────────────────────────────── #
    def _try_resolve(self, comp_id: int) -> bool:
        logger.info("[%s] t.me/s/%s not found — attempting name resolution...",
                    self.name, self.original_name)
        resolved = resolve_username(self.original_name)
        if resolved is None:
            self._mark_unavailable(comp_id, f"could not resolve username for {self.original_name}")
            return False

        new_username = resolved["username"].lower()
        if new_username == self.username.lower():
            return False

        logger.info("[%s] resolved %r -> %r (title=%r)",
                    self.name, self.original_name, new_username, resolved.get("title"))
        _resolved_handle[self.original_name] = new_username
        self.username = new_username

        with session_scope() as s:
            comp = s.get(Competitor, comp_id)
            comp.access_status = SourceAccessStatus.AVAILABLE
            comp.category = _detect_category(resolved.get("title"), new_username) or comp.category
            comp.title = resolved.get("title") or comp.title
        return True

    def _ensure_competitor(self) -> int:
        key = self.original_name
        with session_scope() as s:
            comp = s.scalar(select(Competitor).where(Competitor.username == key))
            if comp is None:
                comp = Competitor(
                    username=key,
                    access_status=SourceAccessStatus.AVAILABLE,
                    discovered_via="config",
                )
                s.add(comp)
                s.flush()
            return comp.id

    def _mark_unavailable(self, comp_id: int, note: str) -> None:
        with session_scope() as s:
            comp = s.get(Competitor, comp_id)
            comp.access_status = SourceAccessStatus.BLOCKED
        logger.warning("[%s] %s: %s", self.name, self.username, note)

    def _touch_timestamp(self, comp_id: int) -> None:
        with session_scope() as s:
            s.get(Competitor, comp_id).last_collected_at = datetime.now(timezone.utc)

    def _emit(self, event_type, entity_type, entity_id, job_id, data) -> None:
        self.bus.publish(
            Event(
                event_type=event_type,
                entity_type=entity_type,
                entity_id=str(entity_id),
                data=data,
                job_id=job_id,
            )
        )
