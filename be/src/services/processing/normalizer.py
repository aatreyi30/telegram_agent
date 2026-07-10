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
        since last time, or normalized under an older NORMALIZATION_VERSION."""
        existing = select(
            NormalizedPost.source_id,
            NormalizedPost.raw_content_sha256,
            NormalizedPost.normalization_version,
        ).where(NormalizedPost.source_type == source_type)
        norm_map = {sid: (sha, ver) for sid, sha, ver in s.execute(existing).all()}

        pending = []
        stmt = select(model).order_by(model.id)
        for raw in s.scalars(stmt):
            prior = norm_map.get(raw.id)
            if (
                prior is None
                or prior[0] != raw.content_sha256
                or prior[1] < NORMALIZATION_VERSION
            ):
                pending.append(raw)
            if len(pending) >= limit:
                break
        return pending

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
        merchant_keys = []
        for u in all_urls:
            mk = detect_merchant_key(u)
            merchant_keys.append(mk)

        # primary merchant = most common KNOWN merchant across links (never guessed)
        known = [m for m in merchant_keys if m]
        primary_merchant = None
        primary_conf = None
        if known:
            counts = Counter(known)
            primary_merchant, top = counts.most_common(1)[0]
            primary_conf = round(top / len(all_urls), 3)  # share of links that agree
            logger.info("[normalizer] merchant detection: source_id=%d primary_merchant=%s confidence=%s known_merchants=%s", raw.id, primary_merchant, primary_conf, dict(counts))

        confidence = self._completeness(bool(prices), bool(all_urls), primary_merchant is not None)

        # upsert: delete a stale NormalizedPost (children cascade) then recreate
        existing = s.scalar(
            select(NormalizedPost).where(
                NormalizedPost.source_type == source_type,
                NormalizedPost.source_id == raw.id,
            )
        )
        is_update = existing is not None
        if existing is not None:
            s.delete(existing)
            s.flush()

        np = NormalizedPost(
            source_type=source_type,
            source_id=raw.id,
            normalization_version=NORMALIZATION_VERSION,
            normalized_at=datetime.now(timezone.utc),
            raw_content_sha256=raw.content_sha256,
            language="unknown",  # language detection deferred (no guessing)
            emojis=emojis or None,
            hashtags=hashtags or None,
            mentions=mentions or None,
            cta_texts=ctas or None,
            num_links=len(all_urls),
            num_prices=len(prices),
            has_coupon=bool(coupons),
            price_threshold=threshold,
            is_multi_deal=len(all_urls) > 1,
            primary_merchant_key=primary_merchant,
            primary_merchant_confidence=primary_conf,
            extraction_confidence=confidence,
        )
        s.add(np)
        s.flush()
        logger.info("[normalizer] normalized_post created: id=%d source_type=%s source_id=%d num_links=%d", np.id, source_type, raw.id, len(all_urls))

        for pm in prices:
            s.add(ExtractedPrice(
                normalized_post_id=np.id, amount=pm.amount, currency=pm.currency,
                raw_text=pm.raw_text, char_position=pm.position,
            ))
        for code, raw_text in coupons:
            s.add(ExtractedCoupon(normalized_post_id=np.id, code=code, raw_text=raw_text))
        for u, info, mk in zip(all_urls, link_infos, merchant_keys):
            s.add(ExtractedLink(
                normalized_post_id=np.id, url=u, domain=info.domain,
                is_shortlink=info.is_shortlink, merchant_key=mk,
                tracking_params=info.tracking_params,
            ))
        logger.info("[normalizer] extracted_links created: normalized_post_id=%d link_count=%d", np.id, len(all_urls))

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
