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

Fairness & resiliency notes:
  * The pending query is ordered ``resolution_attempts ASC, id ASC`` so
    never-attempted links (NULL/0) always get their first shot before we spend
    the run re-trying already-failed backlog. Without this, a large NULL-order
    scan against a multi-thousand-row backlog starves fresh candidates
    indefinitely — a batch of never-attempted Flipkart fkrt.* shortlinks could
    sit at ``resolution_attempts=0`` forever while older stuck rows got
    reselected every run.
  * Some shortener hosts (e.g. ajiio.cc, fktr.cc) serve an INCOMPLETE TLS
    certificate chain (missing intermediate CA), so certifi can't verify and
    httpx raises a generic ConnectError/HTTPError whose message carries a
    ``CERTIFICATE_VERIFY_FAILED`` marker. For that one narrow case only we
    retry the SINGLE request over a ``verify=False`` client. This is safe here
    because we only ever read a redirect target (a URL) from a public marketing
    shortlink — we never send credentials nor trust response-body content. It
    is a fallback ONLY: never a first attempt, and never used for any other
    failure kind.
  * Momentary connection resets / timeouts get up to 2 bounded retries with a
    short backoff before being recorded as a genuine failure. A host proven
    unreachable at the connection level within a run is then skipped for its
    remaining URLs (per-run circuit breaker) so we don't burn the full retry
    budget over and over against a host that's clearly down right now.

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
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import httpx
import tldextract
from sqlalchemy import func, or_, select

from src.services.collection.base import BaseCollector, CollectorResult
from src.services.collection.merchants.registry import detect_merchant_key
from src.config.settings import get_settings
from src.db.models_normalization import DiscoveredDomain, ExtractedLink, NormalizedPost
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus
from src.logger import get_logger

logger = get_logger(__name__)

# The three resolution-outcome states (written to ExtractedLink.resolution_status
# and carried on _ResolveOutcome.status). Named once here because the same three
# string values are asserted/branched on in many places below — a stray typo in
# any one of them would silently mis-record a link's state.
_STATUS_RESOLVED = "resolved"
_STATUS_FAILED = "failed"
_STATUS_NO_MATCH = "no_match"

# Exceptions we treat as an explicit, retryable resolution failure (never a
# bare `except:` — a genuine programming error should still surface).
_RESOLUTION_EXCEPTIONS = (httpx.HTTPError, ssl.SSLError)

# Momentary connection-level failures (resets / timeouts) — as opposed to a
# permanent block or a broken cert chain. These get a short, bounded retry
# (see `_TRANSIENT_BACKOFFS`) before being recorded as a genuine failure.
# Cert-chain failures are deliberately NOT here: they surface as ConnectError
# too, but retrying identically won't fix a server's missing intermediate CA —
# those take the verify=False fallback in `_fetch` instead.
_TRANSIENT_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
)
# Per-attempt backoff (seconds) for transient failures; its length is also the
# retry budget (2 retries => 3 total attempts).
_TRANSIENT_BACKOFFS = (1.0, 2.0)

# Connection-level failures that, once seen for a host this run, trip the
# per-run circuit breaker (skip that host's other URLs). A cert-chain failure
# is intentionally excluded — it's handled by the verify=False fallback, not by
# giving up on the host.
_HOST_DOWN_EXCEPTIONS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)

# Substrings that identify a broken *remote* TLS certificate chain (server sent
# an incomplete chain / missing intermediate CA). httpx surfaces this as a
# generic ConnectError/HTTPError whose message (often on the chained cause)
# contains one of these markers, NOT as a distinctly-typed ssl.SSLError — so we
# match on the message text across the exception and its cause/context.
_CERT_CHAIN_MARKERS = (
    "CERTIFICATE_VERIFY_FAILED",
    "certificate verify failed",
    "unable to get local issuer certificate",
)


def _is_cert_chain_error(exc: BaseException) -> bool:
    """True if `exc` (or its chained cause/context) reports a broken remote TLS
    certificate chain — the narrow case eligible for the verify=False retry."""
    parts = [str(exc)]
    for attr in ("__cause__", "__context__"):
        chained = getattr(exc, attr, None)
        if chained is not None:
            parts.append(str(chained))
    blob = " ".join(parts)
    return any(marker in blob for marker in _CERT_CHAIN_MARKERS)


# Cap on resolution_attempts before a candidate is left alone (still NULL
# merchant/resolved_url, but no longer re-queued every run).
_MAX_ATTEMPTS = 5

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


# Affiliate-redirector networks (NOT merchants). They end on their own page but carry
# the real destination in a query param, and their domain must never be slugged into a
# bogus merchant_key. Param NAMES vary per network (linkredirect.in ?dl=, affinity.net
# ?d=, ...), so we scan every param rather than whitelist names.
_REDIRECTOR_DOMAINS = {
    "affinity.net", "linkredirect.in", "bitli.in", "ddime.in",
}


def _merchant_from_embedded_url(chain: list[str]) -> str | None:
    """Recover a merchant from a destination URL embedded in a redirect's query params.
    Affiliate redirectors carry the real target as a URL-valued query param under a
    provider-specific name (?dl=, ?d=, ?url=, ...), so scan EVERY param value across the
    chain for the first that URL-decodes to a known merchant."""
    for link in chain:
        try:
            params = parse_qs(urlsplit(link).query)
        except ValueError:
            continue
        for values in params.values():
            for raw in values:
                candidate = unquote(raw)
                if candidate.startswith(("http://", "https://")):
                    mk = detect_merchant_key(candidate)
                    if mk:
                        return mk
    return None


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
    status: str  # _STATUS_RESOLVED | _STATUS_FAILED | _STATUS_NO_MATCH
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
                )
                # Prioritise never-attempted links (NULL/0) ahead of
                # already-attempted-and-failed backlog so fresh candidates
                # always get their first shot; oldest-first (id ASC) within an
                # attempt tier keeps it fair/FIFO. Without this explicit order,
                # the default scan starves newly-arrived rows behind a large
                # stuck backlog (the Flipkart fkrt.* starvation). COALESCE maps
                # NULL to 0 so untouched rows sort together with attempts=0.
                .order_by(
                    func.coalesce(ExtractedLink.resolution_attempts, 0).asc(),
                    ExtractedLink.id.asc(),
                )
                .limit(self.limit)
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
        # Hosts proven unreachable at the connection level during THIS run —
        # shared across the concurrent tasks (asyncio is single-threaded, so
        # plain-set mutation is safe) to short-circuit the per-run circuit
        # breaker in `_fetch`.
        down_hosts: set[str] = set()
        client_kwargs = dict(
            http2=True,
            limits=httpx.Limits(max_connections=250, max_keepalive_connections=50),
            timeout=timeout,
            headers={"User-Agent": self.ua},
        )
        # `insecure_client` (verify=False) is used ONLY as the narrow fallback
        # for a broken remote cert chain (see `_fetch`); never as a first
        # attempt and never for other failures.
        async with httpx.AsyncClient(**client_kwargs) as client, \
                httpx.AsyncClient(verify=False, **client_kwargs) as insecure_client:

            async def _bounded(url: str) -> _ResolveOutcome:
                async with sem:
                    return await self._resolve_one(
                        client, insecure_client, cache, url,
                        domain_by_url.get(url), down_hosts,
                    )

            outcomes = await asyncio.gather(*[_bounded(u) for u in by_url])

        affected_posts: set[int] = set()
        with session_scope() as s:
            for outcome in outcomes:
                entries = by_url[outcome.url]

                # write-through: make this run's resolution visible to any
                # later candidate sharing the same URL (already deduped above,
                # but also benefits any future run reading this cache anew).
                if outcome.status != _STATUS_FAILED:
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

                    if outcome.status == _STATUS_FAILED:
                        link.resolution_status = _STATUS_FAILED
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
        down_hosts: set[str],
    ) -> httpx.Response:
        """Perform a single ``GET`` (following redirects) with the run's
        resiliency policy layered on:

          * per-run circuit breaker — if this URL's host was already proven
            unreachable this run, fail fast instead of re-spending the full
            retry-with-backoff budget on a host that's clearly down now;
          * broken-remote-cert fallback — on a ``CERTIFICATE_VERIFY_FAILED``
            style error only, retry this ONE request over `insecure_client`
            (verify=False). Safe: we only read a redirect target from a public
            marketing shortlink, never sending credentials nor trusting body;
          * bounded transient retry — momentary resets / timeouts get up to
            ``len(_TRANSIENT_BACKOFFS)`` retries with backoff.

        Raises the underlying `_RESOLUTION_EXCEPTIONS` on unrecoverable failure;
        the caller records that as an explicit resolution failure."""
        host = (urlsplit(url).hostname or "").lower()
        if host and host in down_hosts:
            raise httpx.ConnectError(f"host {host} marked unreachable earlier this run")

        for attempt in range(len(_TRANSIENT_BACKOFFS) + 1):
            try:
                return await client.get(url, follow_redirects=True)
            except _RESOLUTION_EXCEPTIONS as exc:  # noqa: BLE001 - narrow, re-raised below
                if _is_cert_chain_error(exc):
                    # Broken remote cert chain: retry this single request
                    # insecurely. Not retried further and never trips the
                    # breaker — the host is reachable, only its chain is broken.
                    logger.warning(
                        "[link_resolution] broken remote cert chain for %s, "
                        "retrying once with verify=False: %s", url, exc,
                    )
                    return await insecure_client.get(url, follow_redirects=True)
                if isinstance(exc, _TRANSIENT_EXCEPTIONS) and attempt < len(_TRANSIENT_BACKOFFS):
                    await asyncio.sleep(_TRANSIENT_BACKOFFS[attempt])
                    continue
                # Non-transient, or retries exhausted. If it's a connection-level
                # failure, trip the per-run breaker for this host.
                if host and isinstance(exc, _HOST_DOWN_EXCEPTIONS):
                    down_hosts.add(host)
                raise
        # Unreachable: the loop either returns or raises on every path.
        raise httpx.ConnectError(f"exhausted retries resolving {url}")  # pragma: no cover

    # ------------------------------------------------------------------ #
    async def _resolve_one(
        self,
        client: httpx.AsyncClient,
        insecure_client: httpx.AsyncClient,
        cache: dict[str, tuple[str | None, str | None]],
        url: str,
        raw_domain: str | None,
        down_hosts: set[str],
    ) -> _ResolveOutcome:
        """Resolve a single (deduped) URL: cache hit -> direct-domain match ->
        network fetch + redirect-chain scan -> domain-capture fallback."""
        cached = cache.get(url)
        if cached is not None:
            resolved_url, merchant_key = cached
            status = _STATUS_RESOLVED if merchant_key else _STATUS_NO_MATCH
            return _ResolveOutcome(url, resolved_url, merchant_key, status)

        # self-domain (platform's own domain, WhatsApp, Telegram) — never a
        # merchant; short-circuit before any network call. Excludes grbn.in
        # (see _SELF_DOMAINS_PREFETCH) since that domain must still be
        # followed to reveal the real merchant behind the shortlink.
        if _is_self_domain(raw_domain, _SELF_DOMAINS_PREFETCH):
            return _ResolveOutcome(url, url, None, _STATUS_NO_MATCH)

        # raw link already on a known merchant domain — no network call needed
        if raw_domain:
            direct = detect_merchant_key(raw_domain)
            if direct:
                return _ResolveOutcome(url, url, direct, _STATUS_RESOLVED)

        try:
            response = await self._fetch(client, insecure_client, url, down_hosts)
        except _RESOLUTION_EXCEPTIONS as exc:
            logger.warning("[link_resolution] failed to resolve %s: %s", url, exc)
            return _ResolveOutcome(url, None, None, _STATUS_FAILED, error=str(exc)[:500])

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
                response = await self._fetch(client, insecure_client, next_url, down_hosts)
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

        # Affiliate redirectors (e.g. linkredirect.in) often stop on a landing/error
        # page but carry the real destination in a query param (e.g. ?dl=<merchant-url>).
        # Recover the merchant from that embedded URL before the generic domain-capture.
        if merchant is None:
            merchant = _merchant_from_embedded_url(redirect_chain)

        discovered_domain = None
        if merchant is None:
            merchant, discovered_domain = self._capture_domain(final_url)

        status = _STATUS_RESOLVED if merchant else _STATUS_NO_MATCH
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
        # Never slug the platform's own domain or an affiliate redirector into a
        # "merchant" — the real store lives in the redirector's query param, not its host.
        if _is_self_domain(domain) or domain in _REDIRECTOR_DOMAINS:
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
                    # Share of known-merchant links that agree — same denominator
                    # basis as normalizer's primary_merchant_confidence, so the
                    # field's meaning is stable across resolution.
                    np.primary_merchant_confidence = round(n / len(keys), 3)
                    updated += 1
        return updated
