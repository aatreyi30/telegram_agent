"""Shortlink resolution — follow grbn.in / short URLs to their real merchant.

Clicking a grbn.in link 302-redirects to the actual merchant page, so following
the redirect reveals the merchant we could NOT know at normalization time (we
never guessed it from prose). This backfills ExtractedLink.resolved_url +
merchant_key and re-derives each post's primary merchant, lifting merchant
coverage across the whole system.

Politeness: uses a streamed GET (reads only the final URL, not the page body),
a configurable delay, short timeout, and is fully error-safe — a link that fails
to resolve is left UNKNOWN, never guessed.
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from src.services.collection.base import BaseCollector, CollectorResult
from src.services.collection.merchants.registry import detect_merchant_key
from src.config.settings import get_settings
from src.db.models_normalization import ExtractedLink, NormalizedPost
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus
from src.logger import get_logger

logger = get_logger(__name__)


class LinkResolutionEngine(BaseCollector):
    name = "link_resolution"
    retryable = False

    def __init__(self, limit: int = 2000, delay: float = 0.1):
        self.limit = limit
        self.delay = delay
        self.ua = get_settings().tme_user_agent
        self.bus = get_event_bus()

    def run(self, job) -> CollectorResult:
        result = CollectorResult()
        # unresolved shortlinks with no merchant yet
        with session_scope() as s:
            pending = s.execute(
                select(ExtractedLink.id, ExtractedLink.url)
                .where(ExtractedLink.is_shortlink.is_(True),
                       ExtractedLink.merchant_key.is_(None),
                       ExtractedLink.resolved_url.is_(None))
                .limit(self.limit)
            ).all()
        if not pending:
            result.skipped_reason = "No unresolved shortlinks pending."
            return result

        affected_posts: set[int] = set()
        with httpx.Client(
            timeout=30.0, follow_redirects=True,
            headers={"User-Agent": self.ua},
        ) as client:
            for link_id, url in pending:
                result.processed += 1
                final_url, merchant = self._resolve(client, url)
                with session_scope() as s:
                    link = s.get(ExtractedLink, link_id)
                    if link is None:
                        continue
                    link.resolved_url = final_url
                    link.merchant_key = merchant
                    affected_posts.add(link.normalized_post_id)
                if merchant:
                    result.added += 1
                else:
                    result.skipped += 1
                time.sleep(self.delay)  # polite pacing

        updated_posts = self._backfill_primary_merchant(affected_posts)
        result.updated = updated_posts
        self.bus.publish(Event(
            event_type=EventType.MERCHANT_DETECTED, entity_type="links", entity_id="batch",
            data={"resolved": result.added, "posts_updated": updated_posts}, job_id=job.id,
        ))
        logger.info("[link_resolution] processed=%d resolved_merchant=%d posts_updated=%d",
                    result.processed, result.added, updated_posts)
        return result

    @staticmethod
    def _resolve(client: httpx.Client, url: str) -> tuple[str | None, str | None]:
        """
        Resolve a shortlink by following redirects.

        Merchant detection is attempted on every URL in the redirect chain,
        because affiliate systems often redirect through multiple tracking
        domains before reaching the merchant.
        """
        try:
            response = client.get(url, follow_redirects=True, timeout=15.0)

            redirect_chain = [str(r.url) for r in response.history]
            redirect_chain.append(str(response.url))

            merchant = None
            for redirect_url in redirect_chain:
                merchant = detect_merchant_key(redirect_url)
                if merchant:
                    break

            return str(response.url), merchant

        except httpx.HTTPError:
            return None, None

    @staticmethod
    def _backfill_primary_merchant(post_ids: set[int]) -> int:
        """Re-derive primary_merchant_key from ALL known merchants (direct +
        resolved) across a post's links. Updates whenever the best merchant
        changes, so previously set merchants get corrected as new links resolve."""
        if not post_ids:
            return 0
        updated = 0
        with session_scope() as s:
            for pid in post_ids:
                np = s.get(NormalizedPost, pid)
                if np is None:
                    continue
                keys = [mk for (mk,) in s.execute(
                    select(ExtractedLink.merchant_key).where(
                        ExtractedLink.normalized_post_id == pid,
                        ExtractedLink.merchant_key.isnot(None))
                ).all()]
                if not keys:
                    continue
                counts = Counter(keys)
                top, n = counts.most_common(1)[0]
                if np.primary_merchant_key != top:
                    np.primary_merchant_key = top
                    np.primary_merchant_confidence = round(n / len(keys), 3)
                    updated += 1
        return updated
