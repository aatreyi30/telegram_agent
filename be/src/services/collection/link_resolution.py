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
  * Two failure modes get an extra safety net before being recorded as failed
    (see `_fetch`): a remote server with a broken cert chain (missing
    intermediate CA — fails identically on every attempt) gets ONE retry,
    unverified; a connection reset/timeout (often a transient blip) gets up
    to `_MAX_TRANSIENT_RETRIES` retries with backoff. A host that is
    genuinely blocking us will still fail after these — this narrows false
    "Unknown merchant" results without ever fabricating a resolution.

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
from urllib.parse import urljoin, urlsplit

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

# httpx/httpcore does NOT preserve ssl.SSLError as a catchable type or even as
# `exc.__cause__` — a broken remote cert chain surfaces as a generic
# httpx.ConnectError whose *message* happens to contain the underlying SSL
# reason. So detection has to be by message content, not isinstance().
_CERT_CHAIN_ERROR_MARKERS = (
    "CERTIFICATE_VERIFY_FAILED",
    "certificate verify failed",
    "unable to get local issuer certificate",
)

# Bounded retry for connection-level failures (timeouts, connection resets)
# that are frequently transient network blips rather than a permanent block.
_MAX_TRANSIENT_RETRIES = 2
_TRANSIENT_RETRY_BACKOFF = (1.0, 2.0)  # seconds, one per retry attempt


def _is_cert_chain_error(exc: Exception) -> bool:
    """True if `exc` is a TLS failure caused by the REMOTE server sending an
    incomplete certificate chain (missing intermediate CA) rather than a
    genuinely untrustworthy/misissued cert. Safe to retry unverified for —
    we only ever read the redirect target of a public marketing shortlink
    here, never send credentials or act on response content beyond a URL."""
    text = str(exc)
    return any(marker in text for marker in _CERT_CHAIN_ERROR_MARKERS)


class _DeadDomainError(httpx.TransportError):
    """Raised without any network call when this run already proved the
    URL's host is unreachable (TCP/connection-level, not a cert issue) —
    avoids repeating a doomed multi-attempt-with-backoff fetch for every
    other URL on the same dead host within one run."""

# The platform's own domain plus self-promo/utility domains (WhatsApp,
# Telegram itself). A link that resolves to one of these is never a
# merchant — it's either a self-referral or app-share/deeplink noise — so it
# must never be captured as a `merchant_key` via the generic domain-capture
# fallback, nor treated as a "known merchant domain" shortcut.
#
# NOTE: `grbn.in` is deliberately included here (it's the platform's own
# domain too) so that if resolution ever terminates *still on* grbn.in (a
# dead/self-referential shortlink that never actually redirects anywhere),
# `_capture_domain` doesn't fabricate a bogus "grbn" merchant out of it.
_SELF_DOMAINS = {
    "grabon.in", "www.grabon.in", "grbn.in",
    "whatsapp.com", "wa.me", "chat.whatsapp.com",
    "t.me", "telegram.me", "telegram.org",
}

# Subset used for the PRE-fetch short-circuit in `_resolve_one` (checked
# against the RAW, pre-redirect domain). This deliberately excludes
# `grbn.in`: it's the platform's own shortener (see
# `processing.parser._SHORTENER_DOMAINS`) whose entire purpose is to be
# followed to the real merchant behind it — a raw link on grbn.in must still
# be fetched, unlike the other entries here which are already final
# destinations and never need a network round-trip to know they're not a
# merchant.
_SELF_DOMAINS_PREFETCH = _SELF_DOMAINS - {"grbn.in"}


def _is_self_domain(domain: str | None, domains: frozenset | set = _SELF_DOMAINS) -> bool:
    """True if `domain` (a bare host, e.g. "www.grabon.in" or "t.me") is in
    `domains` (default `_SELF_DOMAINS`) or a subdomain thereof."""
    if not domain:
        return False
    d = domain.lower()
    return d in domains or any(d.endswith("." + s) for s in domains)


# Max number of extra hops we'll follow via meta-refresh / simple-JS redirects
# beyond the HTTP 3xx chain (bounds the loop against redirect cycles).
_MAX_HTML_REDIRECT_HOPS = 2

# <meta http-equiv="refresh" content="N; url=...">  (case-insensitive; the delay
# and url ordering/quoting varies, so match loosely and pull the url out after).
_META_REFRESH_RE = re.compile(
    r"""<meta[^>]*?http-equiv\s*=\s*["']?refresh["']?[^>]*?content\s*=\s*"""
    r"""["']([^"']+)["'][^>]*>""",
    re.IGNORECASE | re.DOTALL,
)
_META_CONTENT_URL_RE = re.compile(
    r"""url\s*=\s*['"]?\s*([^'"\s;]+)""", re.IGNORECASE
)

# Simple JS bounces: window.location = "...", window.location.href = "...",
# window.location.assign("..."), location.replace("...").
_JS_REDIRECT_RE = re.compile(
    r"""(?:window\.)?location(?:\.href)?\s*=\s*['"]([^'"]+)['"]"""
    r"""|(?:window\.)?location\.(?:assign|replace)\s*\(\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)


def _extract_html_redirect(html: str, base_url: str) -> tuple[str | None, float]:
    """Best-effort extraction of a client-side redirect target from an HTML
    body. Handles ``<meta http-equiv="refresh">`` (honouring its delay) and a
    few simple ``window.location`` / ``location.replace`` JS bounces.

    Returns ``(absolute_url_or_None, delay_seconds)``. Relative targets are
    resolved against ``base_url``. Never raises — a non-HTML / unparseable body
    just yields ``(None, 0.0)``."""
    try:
        # meta-refresh takes precedence (it's the declarative, delay-bearing form)
        m = _META_REFRESH_RE.search(html)
        if m:
            content = m.group(1)
            delay = 0.0
            head = content.split(";", 1)[0].strip()
            try:
                delay = float(head)
            except ValueError:
                delay = 0.0
            u = _META_CONTENT_URL_RE.search(content)
            if u:
                return urljoin(base_url, u.group(1).strip()), delay

        # simple JS location assignment
        j = _JS_REDIRECT_RE.search(html)
        if j:
            target = j.group(1) or j.group(2)
            if target:
                return urljoin(base_url, target.strip()), 0.0
    except Exception:  # pragma: no cover - parsing must never crash resolution
        return None, 0.0
    return None, 0.0


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

    def __init__(
        self,
        limit: int = 2000,
        delay: float = 0.1,
        concurrency: int | None = None,
        timeout: float | None = None,
    ):
        self.limit = limit
        # `delay` is kept for backward-compatible call sites (cli.py); the old
        # per-request sleep no longer applies now that requests run
        # concurrently under a semaphore + bounded connection pool.
        self.delay = delay
        # Optional overrides (default None -> today's behaviour, byte-for-byte):
        # `concurrency` falls back to `settings.link_resolve_concurrency` (200,
        # tuned for the live scheduler); callers like a manual backfill script
        # that want a conservative cap (e.g. 10) without touching the global
        # setting pass it explicitly here. `timeout` falls back to the 30s this
        # engine has always used.
        self.concurrency = concurrency
        self.timeout = timeout
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

        concurrency = self.concurrency if self.concurrency is not None else settings.link_resolve_concurrency
        timeout = self.timeout if self.timeout is not None else 30.0
        sem = asyncio.Semaphore(concurrency)
        headers = {
            "User-Agent": self.ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(max_connections=250, max_keepalive_connections=50),
            timeout=timeout,
            headers=headers,
        ) as client, httpx.AsyncClient(
            # Fallback client used ONLY as a last resort when a remote server's
            # cert chain is broken (see _is_cert_chain_error) — never used for
            # a first attempt.
            http2=True,
            verify=False,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
            timeout=timeout,
            headers=headers,
        ) as insecure_client:
            # per-run circuit breaker: a host proven unreachable at the
            # connection level (not a cert issue) is skipped for every other
            # URL on that host for the rest of this run — see `_fetch`.
            dead_domains: set[str] = set()

            async def _bounded(url: str) -> _ResolveOutcome:
                async with sem:
                    return await self._resolve_one(
                        client, insecure_client, cache, url, domain_by_url.get(url), dead_domains
                    )

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
    async def _fetch(
        self,
        client: httpx.AsyncClient,
        insecure_client: httpx.AsyncClient,
        url: str,
        dead_domains: set[str],
    ) -> httpx.Response:
        """GET `url` with two layered safety nets over the plain request:

        1. Cert-chain fallback (one extra attempt): if the failure is a
           broken remote cert chain (see `_is_cert_chain_error`), retry once,
           unverified, ONLY for that one request. Deterministic servers with
           this misconfiguration fail identically every time on a normal
           request, so without this they would NEVER resolve.
        2. Transient-failure retry (bounded, with backoff): connection resets
           and timeouts are frequently momentary network blips, not a
           permanent block — retried up to `_MAX_TRANSIENT_RETRIES` times
           before being recorded as a genuine failure. A host that is
           actually blocking us will still fail after these retries; this
           does not (and cannot) fabricate a resolution for a real block.

        A host proven unreachable at the connection level (not a cert issue)
        is added to `dead_domains` for the rest of THIS run — every other
        URL on that host then fails immediately with no network call, instead
        of separately burning the full retry-with-backoff budget (which,
        for a truly dead host, is pure wasted time held against the
        concurrency semaphore).
        """
        host = urlsplit(url).hostname
        if host and host in dead_domains:
            raise _DeadDomainError(f"{host} already unreachable earlier this run")

        last_exc: Exception | None = None
        for attempt in range(_MAX_TRANSIENT_RETRIES + 1):
            try:
                return await client.get(url, follow_redirects=True)
            except _RESOLUTION_EXCEPTIONS as exc:
                if _is_cert_chain_error(exc):
                    try:
                        response = await insecure_client.get(url, follow_redirects=True)
                        logger.warning(
                            "[link_resolution] %s has a broken cert chain "
                            "(missing intermediate CA) — resolved via unverified fallback",
                            url,
                        )
                        return response
                    except _RESOLUTION_EXCEPTIONS as inner_exc:
                        if host:
                            dead_domains.add(host)
                        raise inner_exc from exc
                last_exc = exc
                if attempt < _MAX_TRANSIENT_RETRIES:
                    await asyncio.sleep(_TRANSIENT_RETRY_BACKOFF[attempt])
                    continue
                if host:
                    dead_domains.add(host)
                raise
        if host:
            dead_domains.add(host)
        raise last_exc  # pragma: no cover - loop always returns or raises

    async def _resolve_one(
        self,
        client: httpx.AsyncClient,
        insecure_client: httpx.AsyncClient,
        cache: dict[str, tuple[str | None, str | None]],
        url: str,
        raw_domain: str | None,
        dead_domains: set[str],
    ) -> _ResolveOutcome:
        """Resolve a single (deduped) URL: cache hit -> direct-domain match ->
        network fetch + redirect-chain scan -> domain-capture fallback."""
        cached = cache.get(url)
        if cached is not None:
            resolved_url, merchant_key = cached
            status = "resolved" if merchant_key else "no_match"
            return _ResolveOutcome(url, resolved_url, merchant_key, status)

        # self-domain (platform's own domain, WhatsApp, Telegram) — never a
        # merchant; short-circuit before any network call. Excludes grbn.in
        # (see _SELF_DOMAINS_PREFETCH) since that domain must still be
        # followed to reveal the real merchant behind the shortlink.
        if _is_self_domain(raw_domain, _SELF_DOMAINS_PREFETCH):
            return _ResolveOutcome(url, url, None, "no_match")

        # raw link already on a known merchant domain — no network call needed
        if raw_domain:
            direct = detect_merchant_key(raw_domain)
            if direct:
                return _ResolveOutcome(url, url, direct, "resolved")

        try:
            response = await self._fetch(client, insecure_client, url, dead_domains)
        except _RESOLUTION_EXCEPTIONS as exc:
            logger.warning("[link_resolution] failed to resolve %s: %s", url, exc)
            return _ResolveOutcome(url, None, None, "failed", error=str(exc)[:500])

        redirect_chain = [str(r.url) for r in response.history]
        redirect_chain.append(str(response.url))

        def _scan(chain: list[str]) -> str | None:
            for redirect_url in chain:
                m = detect_merchant_key(redirect_url)
                if m:
                    return m
            return None

        merchant = _scan(redirect_chain)
        final_url = str(response.url)

        # The HTTP 3xx chain revealed no known merchant. Affiliate landing
        # pages often bounce client-side via <meta http-equiv="refresh"> or a
        # simple window.location JS hop, which httpx does NOT follow — so we'd
        # otherwise stop on the redirector/landing domain and capture the WRONG
        # merchant. Follow up to _MAX_HTML_REDIRECT_HOPS such hops, honouring
        # the meta-refresh delay (capped at 2s). An extra-hop network failure
        # degrades gracefully: we keep the best result reached so far.
        hops = 0
        while merchant is None and hops < _MAX_HTML_REDIRECT_HOPS:
            content_type = response.headers.get("content-type", "")
            if content_type and "html" not in content_type.lower():
                break
            next_url, delay = _extract_html_redirect(response.text, final_url)
            if not next_url:
                break
            try:
                await asyncio.sleep(min(max(delay, 0.0), 2.0))
                response = await self._fetch(client, insecure_client, next_url, dead_domains)
            except _RESOLUTION_EXCEPTIONS as exc:
                logger.warning(
                    "[link_resolution] extra-hop failed for %s -> %s: %s",
                    url, next_url, exc,
                )
                break
            for r in response.history:
                redirect_chain.append(str(r.url))
            redirect_chain.append(str(response.url))
            final_url = str(response.url)
            merchant = _scan(redirect_chain)
            hops += 1

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
        if _is_self_domain(domain):
            return None, None
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
