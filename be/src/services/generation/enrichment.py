"""Deal Enrichment Engine (source_truth/06_data_enrichment_engine.md).

The TRUTH LAYER: transforms raw scraped deals into validated, structured deal
objects. Everything downstream (ranking, selection, generation) depends on this.

Strict rules honoured (source_truth/06):
  * NEVER modify raw input — the raw payload is snapshotted immutably.
  * NEVER assume missing price data — missing values stay UNKNOWN / NULL.
  * NEVER fabricate merchant information — merchant comes only from URL domains.
  * ALWAYS mark unknown values explicitly.
  * Loot detection is DATA-DERIVED (discount vs the batch distribution), not a
    hardcoded threshold (RULE 3).

Input raw deal (source_truth/06 contract):
  {title, url, merchant_url, image, scraped_price, scraped_mrp, discount, timestamp}
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.services.collection.merchants.registry import MERCHANT_SEED, detect_merchant_key
from src.services.collection.raw_store import store_raw
from src.services.collection.util import content_hash
from src.db.models import Merchant, SourceAccessStatus
from src.db.models_generation import DealValidity, EnrichedDeal
from src.services.events import Event, EventType, get_event_bus
from src.logger import get_logger

logger = get_logger(__name__)

_TRACKING_PARAMS = {
    "tag", "affid", "affExtParam1", "affExtParam2", "pid", "sub1", "sub2",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "linkCode", "ascsubtag", "cid", "creative", "creativeASIN",
}
_NUM_RE = re.compile(r"[\d,]+(?:\.\d+)?")

# merchant_key -> merchant_type label + whether it is a marketplace
_MERCHANT_TYPE = {row["key"]: row["key"] for row in MERCHANT_SEED}


@dataclass
class RawDeal:
    title: str | None = None
    url: str | None = None
    merchant_url: str | None = None
    image: str | None = None
    scraped_price: str | float | None = None
    scraped_mrp: str | float | None = None
    discount: str | float | None = None
    timestamp: str | None = None
    source: str = "manual"
    # richer fields when the deal source provides them directly (GrabCash API)
    merchant_key: str | None = None      # retailer given by the source (authoritative)
    category: str | None = None
    subcategory: str | None = None
    coupon_code: str | None = None
    deal_score: float | None = None
    external_id: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "RawDeal":
        return cls(
            title=d.get("title"), url=d.get("url"), merchant_url=d.get("merchant_url"),
            image=d.get("image"), scraped_price=d.get("scraped_price"),
            scraped_mrp=d.get("scraped_mrp"), discount=d.get("discount"),
            timestamp=d.get("timestamp"), source=d.get("source", "manual"),
            merchant_key=d.get("merchant_key"), category=d.get("category"),
            subcategory=d.get("subcategory"), coupon_code=d.get("coupon_code"),
            deal_score=d.get("deal_score"), external_id=d.get("external_id"),
        )


def _to_float(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = _NUM_RE.search(str(v))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _clean_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    kept = [kv for kv in parts.query.split("&")
            if kv and kv.split("=")[0] not in _TRACKING_PARAMS]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(kept), ""))


class DealEnrichmentEngine:
    """Enriches a batch of raw deals. Loot detection uses the batch's own
    discount distribution so no threshold is hardcoded."""

    def __init__(self, session: Session):
        self.s = session
        self.bus = get_event_bus()
        # merchant access verdicts (BLOCKED merchants can't be price-verified)
        self._access = {m.key: m.access_status for m in session.scalars(select(Merchant))}

    def enrich_batch(self, raw_deals: list[RawDeal]) -> list[EnrichedDeal]:
        parsed = [self._pre_parse(rd) for rd in raw_deals]
        discounts = [p["discount_percent"] for p in parsed if p["discount_percent"] is not None]
        # data-derived loot threshold: top quartile of observed discounts (>= 4 samples)
        loot_threshold = (statistics.quantiles(discounts, n=4)[-1]
                          if len(discounts) >= 4 else None)
        out = []
        for rd, p in zip(raw_deals, parsed):
            out.append(self._finalize(rd, p, loot_threshold))
        return out

    # ------------------------------------------------------------------ #
    def _pre_parse(self, rd: RawDeal) -> dict:
        # prefer the merchant the source gives directly (authoritative); else detect from URL
        merchant_key = rd.merchant_key or detect_merchant_key(rd.url or "") or detect_merchant_key(rd.merchant_url or "")
        current = _to_float(rd.scraped_price)
        mrp = _to_float(rd.scraped_mrp)
        discount_pct = _to_float(rd.discount)
        # derive discount from prices when not given, but never guess when absent
        if discount_pct is None and current is not None and mrp and mrp > 0 and current <= mrp:
            discount_pct = round((1 - current / mrp) * 100, 1)
        return {"merchant_key": merchant_key, "current": current, "mrp": mrp,
                "discount_percent": discount_pct}

    def _finalize(self, rd: RawDeal, p: dict, loot_threshold: float | None) -> EnrichedDeal:
        merchant_key = p["merchant_key"]
        current, mrp, discount_pct = p["current"], p["mrp"], p["discount_percent"]

        # validity: valid if we have a real discounted price; invalid if current>mrp;
        # unknown if data missing — never assumed.
        if current is None:
            validity = DealValidity.UNKNOWN
        elif mrp is not None and current > mrp:
            validity = DealValidity.INVALID
        elif discount_pct is not None:
            validity = DealValidity.VALID
        else:
            validity = DealValidity.UNKNOWN

        # loot: data-derived (top-quartile discount within the batch). Undetermined
        # when we lack a distribution or a discount for this deal.
        is_loot = None
        if loot_threshold is not None and discount_pct is not None:
            is_loot = discount_pct >= loot_threshold

        # price confidence: completeness + merchant known. When the deal SOURCE
        # provides the merchant + structured prices (GrabCash API), the direct-scrape
        # BLOCKED status is irrelevant — the source already carries verified data.
        source_provided = rd.merchant_key is not None
        conf = 0.0
        if current is not None:
            conf += 0.4
        if mrp is not None:
            conf += 0.2
        if discount_pct is not None:
            conf += 0.2
        if merchant_key and (source_provided
                             or self._access.get(merchant_key) != SourceAccessStatus.BLOCKED):
            conf += 0.2
        conf = round(conf, 3)

        enrichment_source = ["heuristics"]
        if rd.merchant_key:
            enrichment_source.append("source_provided")
        elif merchant_key:
            enrichment_source.append("url_merchant_detection")

        tags = []
        if merchant_key:
            tags.append(merchant_key)
        if rd.category:
            tags.append(rd.category)
        if rd.coupon_code:
            tags.append(f"coupon:{rd.coupon_code}")
        if is_loot:
            tags.append("loot")
        if current is not None:
            tags.append("budget" if current <= 499 else "high-value" if current >= 3000 else "mid")

        deal_id = content_hash(rd.url or rd.title, current, mrp)[:24]
        clean = _clean_url(rd.url)

        # snapshot raw input immutably (never modify raw)
        snap = store_raw(
            self.s, source="deal_raw", source_ref=rd.url or rd.title,
            payload=rd.__dict__,
        )

        existing = self.s.scalar(select(EnrichedDeal).where(EnrichedDeal.deal_id == deal_id))
        now = datetime.now(timezone.utc)
        if existing is None:
            deal = EnrichedDeal(deal_id=deal_id)
            self.s.add(deal)
        else:
            deal = existing
        deal.source = rd.source
        deal.title = rd.title
        deal.url = rd.url
        deal.clean_url = clean
        deal.image = rd.image
        deal.merchant_key = merchant_key
        deal.merchant_type = merchant_key or "unknown"
        # category comes from the source when available (finally real categories)
        deal.category = rd.category or "unknown"
        deal.original_price = mrp
        deal.current_price = current
        deal.discount_percent = discount_pct
        deal.is_loot_deal = is_loot
        deal.deal_validity = validity
        deal.price_confidence_score = conf
        deal.affiliate_link = None  # GrabOn shortener/affiliate integration deferred
        deal.tags = tags or None
        deal.enrichment_source = enrichment_source
        deal.raw_snapshot_id = snap.id
        deal.last_verified_at = now
        self.s.flush()
        return deal
