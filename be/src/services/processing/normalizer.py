"""Post Normalizer (Phase 2).

Consumes raw posts from the storage layer and produces structured entities.
Runs as a batch job ("collect first, process later") over any post that has no
NormalizedPost yet, or whose raw content hash has changed since last time
(re-normalization after an edit). Fully deterministic and offline — merchant
resolution of shortlinks (a network op) is a separate later enrichment pass.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.services.collection.base import BaseCollector, CollectorResult
from src.services.collection.merchants.registry import detect_merchant_key
from src.db.models import CompetitorPost, Post
from src.db.models_normalization import (
    NORMALIZATION_VERSION,
    ExtractedCoupon,
    ExtractedLink,
    ExtractedPrice,
    NormalizedPost,
    SourceType,
)
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus
from src.logger import get_logger
from src.services.processing import parser

logger = get_logger(__name__)

CHUNK = 500


class PostNormalizer(BaseCollector):
    name = "normalizer"
    retryable = False  # deterministic, offline — a failure is a bug, not transient

    def __init__(self, include_owned: bool = True, include_competitor: bool = True):
        self.include_owned = include_owned
        self.include_competitor = include_competitor
        self.bus = get_event_bus()

    def run(self, job) -> CollectorResult:
        result = CollectorResult()
        if self.include_owned:
            self._process_source(SourceType.OWNED, Post, job.id, result)
        if self.include_competitor:
            self._process_source(SourceType.COMPETITOR, CompetitorPost, job.id, result)
        return result

    # ------------------------------------------------------------------ #
    def _process_source(self, source_type: str, model, job_id: int, result: CollectorResult) -> None:
        while True:
            with session_scope() as s:
                rows = self._fetch_pending(s, source_type, model, CHUNK)
                if not rows:
                    break
                emits: list[tuple[str, str, dict]] = []
                for raw in rows:
                    added, updated = self._normalize_one(s, source_type, raw, emits)
                    result.processed += 1
                    result.added += added
                    result.updated += updated
            # emit AFTER the transaction commits (SQLite nested-write safety)
            for etype, entity_id, data in emits:
                self.bus.publish(
                    Event(event_type=etype, entity_type="normalized_post",
                          entity_id=entity_id, data=data, job_id=job_id)
                )

    def _fetch_pending(self, s: Session, source_type: str, model, limit: int):
        """Posts needing (re)normalization: never normalized, content changed
        since last time, or normalized under an older NORMALIZATION_VERSION.

        The pending predicate is pushed into SQL as a correlated NOT EXISTS so
        the DB returns only the rows that need work — no full in-memory scan of
        every Post/NormalizedPost row. A row is *up to date* (skipped) exactly
        when a NormalizedPost exists for it with a matching content hash and a
        current-or-newer normalization version; anything else is pending. This
        is behaviour-identical to the previous per-row dict lookup because
        NormalizedPost has UniqueConstraint(source_type, source_id) — at most
        one NormalizedPost per raw row, so EXISTS reflects that single prior."""
        up_to_date = (
            select(NormalizedPost.id)
            .where(
                NormalizedPost.source_type == source_type,
                NormalizedPost.source_id == model.id,
                NormalizedPost.raw_content_sha256 == model.content_sha256,
                NormalizedPost.normalization_version >= NORMALIZATION_VERSION,
            )
            .exists()
        )
        stmt = select(model).where(~up_to_date).order_by(model.id).limit(limit)
        return list(s.scalars(stmt))

    def _normalize_one(self, s: Session, source_type: str, raw, emits: list) -> tuple[int, int]:
        text = raw.text
        # links: prefer stored raw links, union with text extraction
        stored_links = list(raw.links or [])
        all_urls = list(dict.fromkeys(stored_links + _extract_text_urls(text)))

        prices = parser.parse_prices(text)
        coupons = parser.parse_coupons(text)
        hashtags = parser.parse_hashtags(text)
        mentions = parser.parse_mentions(text)
        emojis = parser.parse_emojis(text)
        ctas = parser.detect_cta_candidates(text)
        threshold = parser.parse_price_threshold(text)

        link_infos = [parser.classify_link(u) for u in all_urls]
        is_multi_deal = len(all_urls) > 1

        # upsert lookup: fetch any prior NormalizedPost for this raw row FIRST,
        # so link-resolution state (resolved_url/resolution_status/.../merchant_key
        # — written only by the network resolver, link_resolution.py:437-447) can
        # be carried forward instead of wiped on re-normalization (S1-c).
        existing = s.scalar(
            select(NormalizedPost).where(
                NormalizedPost.source_type == source_type,
                NormalizedPost.source_id == raw.id,
            )
        )
        is_update = existing is not None
        existing_links_by_url = {l.url: l for l in existing.links} if existing else {}

        merchant_keys = []
        for u in all_urls:
            mk = detect_merchant_key(u)
            if mk is None:
                prior = existing_links_by_url.get(u)
                if prior is not None:
                    mk = prior.merchant_key
            merchant_keys.append(mk)

        # primary merchant = most common KNOWN merchant across links (never guessed)
        known = [m for m in merchant_keys if m]
        primary_merchant = None
        primary_conf = None
        if known:
            counts = Counter(known)
            primary_merchant, top = counts.most_common(1)[0]
            # Denominator = known-merchant links only (NOT all links), matching
            # link_resolution._backfill_primary_merchant so the field keeps the
            # same meaning (share of resolved/known-merchant links that agree)
            # before and after shortlink resolution.
            primary_conf = round(top / len(known), 3)
            logger.info("[normalizer] merchant detection: source_id=%d primary_merchant=%s confidence=%s known_merchants=%s", raw.id, primary_merchant, primary_conf, dict(counts))

        confidence = self._completeness(bool(prices), bool(all_urls), primary_merchant is not None)

        # deal-dimension extraction (deterministic, from the same text/merchant
        # already resolved above — never guessed)
        discount_pct = parser.parse_discount_pct(text)
        discount_band = parser.discount_band(discount_pct)
        price_band = parser.price_band(prices, threshold, is_multi_deal=is_multi_deal)
        category = parser.infer_category(text, primary_merchant)

        # upsert IN PLACE: reuse the existing row (and its links, by url) rather
        # than delete+recreate. Delete+recreate used to cascade away
        # ExtractedLink.resolved_url/resolution_status/resolution_error/
        # resolution_attempts (network-resolver-only state) and PostClassification
        # rows on every re-normalization — see S1-c. Prices/coupons carry no
        # external state, so those are still fully replaced from the fresh parse.
        if existing is not None:
            np = existing
            for pm in list(np.prices):
                s.delete(pm)
            for cp in list(np.coupons):
                s.delete(cp)
        else:
            np = NormalizedPost(source_type=source_type, source_id=raw.id)
            s.add(np)

        np.normalization_version = NORMALIZATION_VERSION
        np.normalized_at = datetime.now(timezone.utc)
        np.raw_content_sha256 = raw.content_sha256
        np.language = "unknown"  # language detection deferred (no guessing)
        np.emojis = emojis or None
        np.hashtags = hashtags or None
        np.mentions = mentions or None
        np.cta_texts = ctas or None
        np.num_links = len(all_urls)
        np.num_prices = len(prices)
        np.has_coupon = bool(coupons)
        np.price_threshold = threshold
        np.is_multi_deal = is_multi_deal
        np.primary_merchant_key = primary_merchant
        np.primary_merchant_confidence = primary_conf
        np.extraction_confidence = confidence
        np.category = category
        np.discount_pct = discount_pct
        np.discount_band = discount_band
        np.price_band = price_band
        s.flush()
        logger.info("[normalizer] normalized_post upserted: id=%d source_type=%s source_id=%d num_links=%d", np.id, source_type, raw.id, len(all_urls))

        for pm in prices:
            s.add(ExtractedPrice(
                normalized_post_id=np.id, amount=pm.amount, currency=pm.currency,
                raw_text=pm.raw_text, char_position=pm.position,
            ))
        for code, raw_text in coupons:
            s.add(ExtractedCoupon(normalized_post_id=np.id, code=code, raw_text=raw_text))

        # links: update in place for urls seen before (preserves resolver-only
        # columns, which are simply left untouched here), drop urls that
        # disappeared from the post, add brand-new urls.
        new_url_set = set(all_urls)
        for url, link in existing_links_by_url.items():
            if url not in new_url_set:
                s.delete(link)
        for u, info, mk in zip(all_urls, link_infos, merchant_keys):
            link = existing_links_by_url.get(u)
            if link is not None:
                link.domain = info.domain
                link.is_shortlink = info.is_shortlink
                link.merchant_key = mk
                link.tracking_params = info.tracking_params
            else:
                s.add(ExtractedLink(
                    normalized_post_id=np.id, url=u, domain=info.domain,
                    is_shortlink=info.is_shortlink, merchant_key=mk,
                    tracking_params=info.tracking_params,
                ))
        logger.info("[normalizer] extracted_links upserted: normalized_post_id=%d link_count=%d", np.id, len(all_urls))

        # queue events (published after commit)
        emits.append((EventType.POST_NORMALIZED, str(np.id),
                      {"source_type": source_type, "source_id": raw.id}))
        if primary_merchant:
            emits.append((EventType.MERCHANT_DETECTED, str(np.id),
                          {"merchant": primary_merchant, "confidence": primary_conf}))
        if prices:
            emits.append((EventType.PRICE_EXTRACTED, str(np.id),
                          {"count": len(prices)}))
        return (0, 1) if is_update else (1, 0)

    @staticmethod
    def _completeness(has_price: bool, has_link: bool, has_merchant: bool) -> float:
        """Data-COMPLETENESS score (not a judgement of meaning).

        Mirrors source_truth/06's conceptual formula minus API verification
        (deferred): price presence + link presence + merchant match.
        """
        return round(0.4 * has_price + 0.3 * has_link + 0.3 * has_merchant, 3)


def _extract_text_urls(text: str | None) -> list[str]:
    from src.services.collection.util import extract_urls

    return extract_urls(text)
