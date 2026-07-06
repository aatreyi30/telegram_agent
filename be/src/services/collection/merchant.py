"""Merchant enrichment collector.

Given a product URL, detect the merchant, route to the correct MerchantSource,
store the product + a price-history snapshot, and emit events. For BLOCKED
merchants it records the block reason and skips — it never fabricates data.

Phase-1 scope: on-demand enrichment of a supplied URL (matches the Deal
Enrichment Engine input contract, source_truth/06). Automated deal *sourcing*
(feeds) is a later phase.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from src.services.collection.base import BaseCollector, CollectorResult
from src.services.collection.merchants.amazon import AmazonCreatorsSource
from src.services.collection.merchants.base import MerchantSource, ProductData
from src.services.collection.merchants.boat import BoatShopifySource
from src.services.collection.merchants.flipkart import FlipkartAffiliateSource
from src.services.collection.merchants.registry import detect_merchant_key
from src.services.collection.merchants.reliance import RelianceDigitalSource
from src.services.collection.raw_store import store_raw
from src.db.models import (
    Merchant,
    MerchantProduct,
    ProductPriceSnapshot,
    SourceAccessStatus,
)
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus
from src.logger import get_logger

logger = get_logger(__name__)

# All implemented sources. BLOCKED merchants intentionally have none.
_SOURCES: list[MerchantSource] = [
    BoatShopifySource(),
    RelianceDigitalSource(),
    AmazonCreatorsSource(),
    FlipkartAffiliateSource(),
]


class MerchantEnrichmentCollector(BaseCollector):
    name = "merchant_enrichment"

    def __init__(self, url: str):
        self.url = url.strip()
        self.bus = get_event_bus()

    def _source_for(self, url: str) -> MerchantSource | None:
        for src in _SOURCES:
            if src.matches(url):
                return src
        return None

    def available(self) -> tuple[bool, str | None]:
        key = detect_merchant_key(self.url)
        if key is None:
            return False, f"Unknown merchant for URL: {self.url}"
        with session_scope() as s:
            merchant = s.scalar(select(Merchant).where(Merchant.key == key))
            status = merchant.access_status if merchant else SourceAccessStatus.UNKNOWN
            notes = merchant.access_notes if merchant else None
        if status == SourceAccessStatus.BLOCKED:
            return False, f"Merchant '{key}' is BLOCKED: {notes}"
        src = self._source_for(self.url)
        if src is None:
            return False, f"No collector implemented for merchant '{key}'."
        return src.available()

    def run(self, job) -> CollectorResult:
        result = CollectorResult()
        key = detect_merchant_key(self.url)
        src = self._source_for(self.url)
        if key is None or src is None:
            result.skipped_reason = f"No source for URL: {self.url}"
            return result

        data = src.fetch(self.url)
        result.processed = 1
        if data is None:
            result.skipped_reason = "Product not found / not fetchable."
            return result

        added, updated, product_id, price_changed = self._store(key, data, job.id)
        result.added += added
        result.updated += updated
        self._emit(EventType.PRODUCT_UPDATED, "product", product_id, job.id,
                   {"merchant": key})
        if price_changed:
            self._emit(EventType.PRICE_CHANGED, "product", product_id, job.id,
                       {"merchant": key, "current_price": data.current_price})
        return result

    def _store(self, merchant_key: str, data: ProductData, job_id: int) -> tuple[int, int, int, bool]:
        now = datetime.now(timezone.utc)
        with session_scope() as s:
            merchant = s.scalar(select(Merchant).where(Merchant.key == merchant_key))
            snap = store_raw(
                s,
                source=f"merchant_{merchant_key}",
                source_ref=data.product_url or data.external_id,
                payload=data.raw_payload if data.raw_payload is not None else {},
                job_id=job_id,
                content_type="text/html" if isinstance(data.raw_payload, str) else "application/json",
            )
            existing = s.scalar(
                select(MerchantProduct).where(
                    MerchantProduct.merchant_id == merchant.id,
                    MerchantProduct.external_id == data.external_id,
                )
            )
            price_changed = False
            if existing is None:
                product = MerchantProduct(
                    merchant_id=merchant.id,
                    external_id=data.external_id,
                    title=data.title,
                    brand=data.brand,
                    category_text=data.category_text,
                    product_url=data.product_url,
                    image_url=data.image_url,
                    current_price=data.current_price,
                    mrp=data.mrp,
                    currency=data.currency,
                    availability=data.availability,
                    last_verified_at=now,
                    raw_snapshot_id=snap.id,
                )
                s.add(product)
                s.flush()
                self._add_price_snapshot(s, product.id, data, now)
                return 1, 0, product.id, False

            price_changed = (
                existing.current_price != data.current_price
                and data.current_price is not None
            )
            # only overwrite with observed (non-None) values; keep prior otherwise
            existing.title = data.title or existing.title
            existing.brand = data.brand or existing.brand
            existing.category_text = data.category_text or existing.category_text
            existing.image_url = data.image_url or existing.image_url
            if data.current_price is not None:
                existing.current_price = data.current_price
            if data.mrp is not None:
                existing.mrp = data.mrp
            if data.availability is not None:
                existing.availability = data.availability
            existing.last_verified_at = now
            existing.raw_snapshot_id = snap.id
            self._add_price_snapshot(s, existing.id, data, now)
            return 0, 1, existing.id, price_changed

    @staticmethod
    def _add_price_snapshot(session, product_id: int, data: ProductData, now) -> None:
        if data.current_price is None and data.mrp is None and data.availability is None:
            return  # nothing observed -> no snapshot (never store empty rows)
        session.add(
            ProductPriceSnapshot(
                product_id=product_id,
                captured_at=now,
                current_price=data.current_price,
                mrp=data.mrp,
                availability=data.availability,
            )
        )

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
