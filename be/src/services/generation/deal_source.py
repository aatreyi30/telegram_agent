"""Live deal source connector (the "Scraping Layer" in source_truth/06).

Fetches TODAY's latest deals from the operator's deal-scraping platform, maps
them into the raw-deal contract, and hands them to the Deal Enrichment Engine.
This is the correct input for NEW posts — never recycled historical links.

Configuration (.env):
  DEAL_API_BASE       full URL of the "latest deals" endpoint (required)
  API_SECRET_KEY      credential for the platform
  DEAL_API_AUTH       how the key is sent: "bearer" (Authorization: Bearer <key>),
                      "header:<Name>" (e.g. header:X-API-Key), or "query:<param>"
                      (e.g. query:api_key). Default: bearer.

Honesty: the response FIELD MAPPING below covers common names, but a real API's
schema must be confirmed. `fetch-deals` logs the first raw item so the mapping
can be verified/corrected before trusting generated posts. If DEAL_API_BASE is
unset, the connector reports UNAVAILABLE (it never fabricates deals).
"""

from __future__ import annotations

import os

import httpx

from src.config.settings import get_settings
from src.services.generation.enrichment import RawDeal
from src.logger import get_logger

logger = get_logger(__name__)

# Field names verified against the live GrabCash API response
# (https://deals.grabcash.in/api/v1/deals). Aliases kept for resilience.
_FIELD_ALIASES = {
    "title": ["product_title", "caption", "title", "name", "product_name"],
    "url": ["original_url", "url", "link", "deal_url", "product_url"],
    "merchant_url": ["merchant_url", "store_url", "source_url"],
    "image": ["image_url", "image", "img", "thumbnail"],
    "scraped_price": ["discount_price", "scraped_price", "price", "current_price", "sale_price"],
    "scraped_mrp": ["mrp", "scraped_mrp", "original_price", "list_price"],
    "discount": ["discount_percentage", "discount", "discount_percent", "off"],
    "timestamp": ["ingested_at", "timestamp", "created_at", "posted_at"],
    "merchant_key": ["retailer_key", "merchant_key", "retailer", "store_key"],
    "category": ["category_key", "category"],
    "subcategory": ["subcategory_key", "subcategory"],
    "coupon_code": ["coupon_code", "coupon", "code"],
    "deal_score": ["deal_score", "score"],
    "external_id": ["id", "deal_id", "sno"],
}


def _pick(item: dict, keys: list[str]):
    for k in keys:
        if k in item and item[k] not in (None, ""):
            return item[k]
    return None


def _map_item(item: dict, source: str) -> RawDeal:
    return RawDeal(
        title=_pick(item, _FIELD_ALIASES["title"]),
        url=_pick(item, _FIELD_ALIASES["url"]),
        merchant_url=_pick(item, _FIELD_ALIASES["merchant_url"]),
        image=_pick(item, _FIELD_ALIASES["image"]),
        scraped_price=_pick(item, _FIELD_ALIASES["scraped_price"]),
        scraped_mrp=_pick(item, _FIELD_ALIASES["scraped_mrp"]),
        discount=_pick(item, _FIELD_ALIASES["discount"]),
        timestamp=_pick(item, _FIELD_ALIASES["timestamp"]),
        merchant_key=_pick(item, _FIELD_ALIASES["merchant_key"]),
        category=_pick(item, _FIELD_ALIASES["category"]),
        subcategory=_pick(item, _FIELD_ALIASES["subcategory"]),
        coupon_code=_pick(item, _FIELD_ALIASES["coupon_code"]),
        deal_score=_pick(item, _FIELD_ALIASES["deal_score"]),
        external_id=_pick(item, _FIELD_ALIASES["external_id"]),
        source=source,
    )


def _extract_items(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("deals", "data", "results", "items", "products"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


class DealSourceClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base = os.environ.get("DEAL_API_BASE") or self.settings.grabcash_api_base
        self.key = self.settings.api_secret_key
        self.auth = os.environ.get("DEAL_API_AUTH", "bearer")
        self.source = os.environ.get("DEAL_API_SOURCE", "deal_api")

    def available(self) -> tuple[bool, str | None]:
        if not self.base:
            return False, ("Deal source not configured. Set DEAL_API_BASE to the latest-deals "
                           "endpoint (and API_SECRET_KEY) in .env.")
        return True, None

    def _auth_kwargs(self) -> dict:
        headers, params = {}, {}
        if self.key:
            if self.auth == "bearer":
                headers["Authorization"] = f"Bearer {self.key}"
            elif self.auth.startswith("header:"):
                headers[self.auth.split(":", 1)[1]] = self.key
            elif self.auth.startswith("query:"):
                params[self.auth.split(":", 1)[1]] = self.key
        return {"headers": headers, "params": params}

    def _fetch_httpx(self, want: int, page_size: int) -> list[dict]:
        """Direct API pull (fast path). Raises on Cloudflare 403 / network error."""
        collected: list[dict] = []
        page = 1
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            while len(collected) < want:
                kw = self._auth_kwargs()
                kw["params"] = {**kw.get("params", {}), "page": page, "page_size": page_size}
                resp = client.get(self.base, **kw)
                resp.raise_for_status()
                payload = resp.json()
                items = _extract_items(payload)
                if not items:
                    break
                collected.extend(items)
                total_pages = payload.get("pages") if isinstance(payload, dict) else None
                if total_pages and page >= total_pages:
                    break
                page += 1
        return collected

    def _collect_raw(self, want: int, page_size: int) -> list[dict]:
        """Raw deal dicts via the direct API, falling back to the Camoufox stealth
        browser when Cloudflare blocks the plain client (403)."""
        try:
            items = self._fetch_httpx(want, page_size)
            if items:
                logger.info("[deal_source] fetched %d items via direct API", len(items))
                return items
            logger.warning("[deal_source] direct API returned no items; trying browser")
        except Exception as e:  # 403 / network / schema
            logger.warning("[deal_source] direct API failed (%s); using Camoufox browser", e)
        from src.services.collection.deal_scraper import CamoufoxDealSource
        return CamoufoxDealSource().fetch_raw(want=want, page_size=page_size)

    def fetch_latest(self, limit: int = 20, page_size: int = 60) -> list[RawDeal]:
        """Fetch today's most RELEVANT, attractive deals (real saving, strong
        discount + deal score), ranked most-attractive first, mapped to RawDeal.

        Over-fetches then filters for relevance so the operator only ever posts
        deals worth a customer's attention."""
        ok, reason = self.available()
        if not ok:
            raise RuntimeError(reason)
        from src.services.collection.deal_scraper import diversify_by_category, filter_relevant

        # over-fetch a broad pool so multiple categories are represented, filter for
        # attractiveness, then spread the pick across categories (variety like the
        # channel actually posts) — each category led by its most attractive deals.
        raw = self._collect_raw(want=max(limit * 8, 200), page_size=80)
        relevant = filter_relevant(raw)
        picked = diversify_by_category(relevant, limit=limit)
        logger.info("[deal_source] %d relevant of %d fetched; picked %d across %d categories",
                    len(relevant), len(raw), len(picked),
                    len({p.get("category_key") for p in picked}))
        return [_map_item(it, self.source) for it in picked]
