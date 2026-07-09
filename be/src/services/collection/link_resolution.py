"""Shortlink / unclassified-link resolution — follow redirects to the real
merchant, concurrently, with caching and a generic domain-capture fallback.

Clicking any shortlink or unclassified link may 302-redirect to the actual
merchant page, so following the redirect reveals the merchant we could NOT
know at normalization time. This backfills ExtractedLink.resolved_url
+ merchant_key and re-derives each post's primary merchant, lifting merchant
coverage across the whole system.

Design notes (async rewrite):
  * Candidate selection is no longer gated on ``is_shortlink`` — ANY link with
    no merchant_key and no resolved_url yet is a candidate (capped retries via
    resolution_attempts), because near-miss/variant shortener domains that
    aren't in the static whitelist would otherwise never get queued.
  * If the raw (pre-resolution) domain already matches a known merchant, we
    classify immediately with zero network calls.
  * An in-memory cache (seeded from previously-resolved rows, write-through
    during the run) means a shortlink reused across many posts is only ever
    resolved once.
  * When resolution completes but lands on a domain outside the static
    registry, we do NOT discard it as unknown — we capture the registrable
    domain (via tldextract) as a DiscoveredDomain and use a slug of it as the
    link's merchant_key. This is a deliberately separate, dynamic mechanism;
    it never writes back into the static registry/whitelist.
  * Failures (timeouts, connection errors, SSL errors, HTTP errors) are
    recorded explicitly (resolution_status="failed" + resolution_error) so
    they're distinguishable from "never attempted" and can be retried up to a
    cap, instead of silently looking identical to a NULL resolved_url.

Politeness: still a single AsyncClient with a bounded connection pool and a
concurrency semaphore, so we don't hammer any one host arbitrarily — bounded
by max_connections / semaphore, not a single-file-at-a-time sleep loop.
"""

from __future__ import annotations

import asyncio
import re
import ssl
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import tldextract
from sqlalchemy import or_, select

from src.services.collection.base import BaseCollector, CollectorResult
from src.services.collection.merchants.registry import detect_merchant_key
from src.config.settings import get_settings
from src.db.models_normalization import DiscoveredDomain, ExtractedLink, NormalizedPost
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus
from src.logger import get_logger

logger = get_logger(__name__)

# Exceptions we treat as an explicit, retryable resolution failure (never a
# bare `except:` — a genuine programming error should still surface).
_RESOLUTION_EXCEPTIONS = (httpx.HTTPError, ssl.SSLError)

# Cap on resolution_attempts before a candidate is left alone (still NULL
# merchant/resolved_url, but no longer re-queued every run).
_MAX_ATTEMPTS = 5


@dataclass
class _ResolveOutcome:
    url: str
    resolved_url: str | None
    merchant_key: str | None
    status: str  # "resolved" | "failed" | "no_match"
    error: str | None = None
    discovered_domain: str | None = None  # set only when the capture fallback fired


class LinkResolutionEngine(BaseCollector):
    name = "link_resolution"
    retryable = False

    def __init__(self, limit: int = 2000, delay: float = 0.1):
        self.limit = limit
        # `delay` is kept for backward-compatible call sites (cli.py); the old
        # per-request sleep no longer applies now that requests run
        # concurrently under a semaphore + bounded connection pool.
        self.delay = delay
        self.ua = get_settings().tme_user_agent
        self.bus = get_event_bus()

    def run(self, job) -> CollectorResult:
        return asyncio.run(self._run_async(job))

    # ------------------------------------------------------------------ #
    async def _run_async(self, job) -> CollectorResult:
        result = CollectorResult()
        settings = get_settings()

        with session_scope() as s:
            pending = s.execute(
                select(
                    ExtractedLink.id,
                    ExtractedLink.url,
                    ExtractedLink.domain,
                    ExtractedLink.normalized_post_id,
                ).where(
                    ExtractedLink.merchant_key.is_(None),
                    ExtractedLink.resolved_url.is_(None),
                    or_(
                        ExtractedLink.resolution_attempts.is_(None),
                        ExtractedLink.resolution_attempts < _MAX_ATTEMPTS,
                    ),
                ).limit(self.limit)
            ).all()
        if not pending:
            result.skipped_reason = "No unresolved links pending."
            return result

        # cross-run cache, seeded from links already resolved in the past
        cache: dict[str, tuple[str | None, str | None]] = {}
        with session_scope() as s:
            rows = s.execute(
                select(
                    ExtractedLink.url, ExtractedLink.resolved_url, ExtractedLink.merchant_key
                ).where(ExtractedLink.resolved_url.isnot(None)).distinct()
            ).all()
        for url, resolved_url, merchant_key in rows:
            cache[url] = (resolved_url, merchant_key)

        # dedupe candidates by raw URL up front — a shortlink reused across many
        # posts must only ever be resolved once per run, not once per row.
        by_url: dict[str, list[tuple[int, int]]] = {}
        domain_by_url: dict[str, str | None] = {}
        for link_id, url, domain, post_id in pending:
            by_url.setdefault(url, []).append((link_id, post_id))
            domain_by_url.setdefault(url, domain)

        sem = asyncio.Semaphore(settings.link_resolve_concurrency)
        async with httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(max_connections=250, max_keepalive_connections=50),
            timeout=30.0,
            headers={"User-Agent": self.ua},
        ) as client:

            async def _bounded(url: str) -> _ResolveOutcome:
                async with sem:
                    return await self._resolve_one(client, cache, url, domain_by_url.get(url))

            outcomes = await asyncio.gather(*[_bounded(u) for u in by_url])

        affected_posts: set[int] = set()
        with session_scope() as s:
            for outcome in outcomes:
                entries = by_url[outcome.url]

                # write-through: make this run's resolution visible to any
                # later candidate sharing the same URL (already deduped above,
                # but also benefits any future run reading this cache anew).
                if outcome.status != "failed":
                    cache[outcome.url] = (outcome.resolved_url, outcome.merchant_key)

                if outcome.discovered_domain:
                    self._upsert_discovered_domain(
                        s,
                        domain=outcome.discovered_domain,
                        merchant_key=outcome.merchant_key,
                        sample_url=outcome.resolved_url,
                        sample_post_id=entries[0][1],
                    )

                for link_id, post_id in entries:
                    link = s.get(ExtractedLink, link_id)
                    if link is None:
                        continue
                    result.processed += 1
                    affected_posts.add(post_id)

                    if outcome.status == "failed":
                        link.resolution_status = "failed"
                        link.resolution_error = outcome.error
                        link.resolution_attempts = (link.resolution_attempts or 0) + 1
                        result.skipped += 1
                        continue

                    link.resolved_url = outcome.resolved_url
                    link.merchant_key = outcome.merchant_key
                    link.resolution_status = outcome.status
                    link.resolution_error = None
                    logger.info("[link_resolution] link resolved: link_id=%d url=%s resolved_url=%s merchant_key=%s", link_id, outcome.url, outcome.resolved_url, outcome.merchant_key)
                    if outcome.merchant_key:
                        result.added += 1
                    else:
                        result.skipped += 1

        updated_posts = self._backfill_primary_merchant(affected_posts)
        result.updated = updated_posts
        self.bus.publish(Event(
            event_type=EventType.MERCHANT_DETECTED, entity_type="links", entity_id="batch",
            data={"resolved": result.added, "posts_updated": updated_posts}, job_id=job.id,
        ))
        logger.info("[link_resolution] processed=%d resolved_merchant=%d posts_updated=%d",
                    result.processed, result.added, updated_posts)
        return result

    # ------------------------------------------------------------------ #
    async def _resolve_one(
        self,
        client: httpx.AsyncClient,
        cache: dict[str, tuple[str | None, str | None]],
        url: str,
        raw_domain: str | None,
    ) -> _ResolveOutcome:
        """Resolve a single (deduped) URL: cache hit -> direct-domain match ->
        network fetch + redirect-chain scan -> domain-capture fallback."""
        cached = cache.get(url)
        if cached is not None:
            resolved_url, merchant_key = cached
            status = "resolved" if merchant_key else "no_match"
            return _ResolveOutcome(url, resolved_url, merchant_key, status)

        # raw link already on a known merchant domain — no network call needed
        if raw_domain:
            direct = detect_merchant_key(raw_domain)
            if direct:
                return _ResolveOutcome(url, url, direct, "resolved")

        try:
            response = await client.get(url, follow_redirects=True)
        except _RESOLUTION_EXCEPTIONS as exc:
            logger.warning("[link_resolution] failed to resolve %s: %s", url, exc)
            return _ResolveOutcome(url, None, None, "failed", error=str(exc)[:500])

        redirect_chain = [str(r.url) for r in response.history]
        redirect_chain.append(str(response.url))

        merchant = None
        for redirect_url in redirect_chain:
            merchant = detect_merchant_key(redirect_url)
            if merchant:
                break

        final_url = str(response.url)
        discovered_domain = None
        if merchant is None:
            merchant, discovered_domain = self._capture_domain(final_url)

        status = "resolved" if merchant else "no_match"
        return _ResolveOutcome(url, final_url, merchant, status, discovered_domain=discovered_domain)

    @staticmethod
    def _capture_domain(final_url: str) -> tuple[str | None, str | None]:
        """Generic fallback for a resolved URL that matched no known merchant:
        extract its registrable domain (correct eTLD+1, e.g. handles .co.in)
        and derive a merchant_key slug from it. Returns (merchant_key, domain),
        or (None, None) if the URL has no sensible host to extract (e.g. a
        resolved URL with no host)."""
        try:
            ext = tldextract.extract(final_url)
        except Exception:  # pragma: no cover - tldextract is defensive already
            return None, None
        if not ext.domain or not ext.suffix:
            return None, None
        domain = f"{ext.domain}.{ext.suffix}".lower()
        slug = re.sub(r"[^a-z0-9]+", "_", ext.domain.lower()).strip("_")
        if not slug:
            return None, None
        return slug, domain

    @staticmethod
    def _upsert_discovered_domain(
        s, *, domain: str, merchant_key: str | None, sample_url: str | None, sample_post_id: int | None
    ) -> None:
        now = datetime.now(timezone.utc)
        row = s.get(DiscoveredDomain, domain)
        if row is None:
            s.add(DiscoveredDomain(
                domain=domain,
                merchant_key=merchant_key or domain,
                count=1,
                first_seen=now,
                last_seen=now,
                sample_url=sample_url,
                sample_post_id=sample_post_id,
            ))
        else:
            row.count += 1
            row.last_seen = now

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
