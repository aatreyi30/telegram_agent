"""Competitor collector — public channels via the t.me/s web preview.

Confirmed accessible without authentication (Data Validation Matrix Feature 10).
We store ONLY what the preview exposes: post content, links, visible (often
rounded) view counts, timestamps. Reactions and precise forward counts are NOT
reliably exposed by t.me/s, so they stay NULL — never fabricated.

Acknowledged risk (recorded in the matrix): Telegram may change the preview
format or add bot protection at any time. On parse failure we surface the
error via the job record instead of inventing data.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from src.services.collection.base import BaseCollector, CollectorResult
from src.services.collection.raw_store import store_raw
from src.services.collection.util import content_hash, extract_urls, parse_abbreviated_int, to_utc
from src.config.settings import get_settings
from src.db.models import Competitor, CompetitorPost, SourceAccessStatus
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus
from src.logger import get_logger

logger = get_logger(__name__)

BASE_URL = "https://t.me/s/{username}"


class CompetitorCollector(BaseCollector):
    name = "telegram_competitor"

    def __init__(self, username: str, max_pages: int = 1):
        self.username = username.lstrip("@")
        self.max_pages = max_pages
        self.settings = get_settings()
        self.bus = get_event_bus()

    def run(self, job) -> CollectorResult:
        result = CollectorResult()
        comp_id = self._ensure_competitor()

        before: int | None = None
        pages_done = 0
        with httpx.Client(
            headers={"User-Agent": self.settings.tme_user_agent},
            timeout=30.0,
            follow_redirects=True,
        ) as client:
            while pages_done < self.max_pages:
                url = BASE_URL.format(username=self.username)
                params = {"before": before} if before else None
                resp = client.get(url, params=params)
                if resp.status_code == 404:
                    self._mark_unavailable(comp_id, "t.me/s returned 404 (channel not public?)")
                    result.skipped_reason = "channel not accessible via t.me/s (404)"
                    return result
                resp.raise_for_status()
                # t.me/s/<name> redirects to t.me/<name> when <name> is NOT a
                # public channel with a message preview (user/bot/group/nonexistent).
                # Detect that instead of silently "succeeding" with 0 posts.
                if "/s/" not in str(resp.url):
                    self._mark_unavailable(
                        comp_id,
                        "t.me/s redirected away — not a public channel preview "
                        f"(resolved to {resp.url}). Check the exact @username.",
                    )
                    result.skipped_reason = (
                        f"'{self.username}' has no public t.me/s preview "
                        "(not a public channel, or wrong username)."
                    )
                    return result
                html = resp.text

                with session_scope() as s:
                    store_raw(
                        s,
                        source=self.name,
                        source_ref=f"{self.username}:before={before or ''}",
                        payload=html,
                        job_id=job.id,
                        content_type="text/html",
                    )

                self._update_channel_meta(comp_id, html)
                posts = self._parse_posts(html)
                if not posts:
                    break

                oldest_id = None
                for p in posts:
                    added, updated = self._store_post(comp_id, p, job.id)
                    result.processed += 1
                    result.added += added
                    result.updated += updated
                    oldest_id = p["msg_id"] if oldest_id is None else min(oldest_id, p["msg_id"])

                pages_done += 1
                before = oldest_id
                if before is None:
                    break
                time.sleep(self.settings.tme_request_delay_seconds)  # polite pacing

        with session_scope() as s:
            comp = s.get(Competitor, comp_id)
            comp.last_collected_at = datetime.now(timezone.utc)
        self._emit(EventType.COMPETITOR_UPDATED, "competitor", comp_id, job.id,
                   {"posts_seen": result.processed})
        return result

    # ------------------------------------------------------------------ #
    def _parse_posts(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        out: list[dict] = []
        for node in soup.select(".tgme_widget_message"):
            data_post = node.get("data-post")  # "username/12345"
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
            # explicit anchor hrefs inside the message body, too
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

            out.append(
                {
                    "msg_id": msg_id,
                    "text": text,
                    "views_text": views_text,
                    "posted_at": to_utc(posted_at),
                    "links": links,
                    "has_media": has_media,
                }
            )
        return out

    def _store_post(self, comp_id: int, p: dict, job_id: int) -> tuple[int, int]:
        # NB: events are emitted AFTER the transaction commits (below), never
        # inside an open session — nested write sessions deadlock on SQLite.
        digest = content_hash(p["text"], p["links"])
        new_post_id: int | None = None
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
                    forwards=None,  # not reliably exposed by t.me/s — never guessed
                    collected_at=now,
                )
                s.add(cp)
                s.flush()
                new_post_id = cp.id
                added = 1
            else:
                # update the observable counters + edited text
                changed = existing.content_sha256 != digest
                existing.views_text = p["views_text"]
                existing.views = views_int
                if changed:
                    existing.text = p["text"]
                    existing.content_sha256 = digest
                    existing.links = p["links"] or None
                    updated = 1
        if new_post_id is not None:
            self._emit(EventType.COMPETITOR_POST_COLLECTED, "competitor_post",
                       new_post_id, job_id, {"competitor_id": comp_id})
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

    def _ensure_competitor(self) -> int:
        with session_scope() as s:
            comp = s.scalar(select(Competitor).where(Competitor.username == self.username))
            if comp is None:
                comp = Competitor(
                    username=self.username,
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
            comp.description = (comp.description or "")  # keep; note goes to logs
        logger.warning("[%s] %s: %s", self.name, self.username, note)

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
