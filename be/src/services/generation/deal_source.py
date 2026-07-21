"""Live deal source connector (the "Scraping Layer" in source_truth/06).

Fetches TODAY's latest deals from the GrabCash EXPORT API, one retailer at a
time, maps them into the raw-deal contract, and hands them to the Deal
Enrichment Engine. This is the correct input for NEW posts — never recycled
historical links.

Source: GrabCash export API (https://deals.grabcash.in/api/v1/export/deals).
Auth is a query param (`key=<API_SECRET_KEY>`), unlike the older `/deals`
endpoint which took the key via header/bearer — see DEAL_API_AUTH below,
still used by the Camoufox fallback. Queried once per allowed retailer
(`?retailer=<key>`) so the merchant allow-list is enforced at the source
instead of by filtering an unfiltered over-fetch afterward.

Configuration (.env):
  DEAL_API_BASE       full URL of the legacy "latest deals" endpoint, used
                      only by the Camoufox stealth-browser fallback below
  API_SECRET_KEY      credential for the platform (export API's `key` param)
  DEAL_API_AUTH       how the Camoufox fallback sends the key: "bearer",
                      "header:<Name>" (e.g. header:X-API-Key), or "query:<param>".
                      Default: bearer.

Honesty: the response FIELD MAPPING below covers common names, but a real API's
schema must be confirmed. `fetch-deals` logs the first raw item so the mapping
can be verified/corrected before trusting generated posts. If no API key is
configured, the connector reports UNAVAILABLE (it never fabricates deals).
"""

from __future__ import annotations

import os

import httpx

from src.config.settings import get_settings
from src.services.collection.deal_scraper import ALLOWED_MERCHANTS
from src.services.generation.constants import PRICE_FIELD_ALIASES
from src.services.generation.enrichment import RawDeal
from src.logger import get_logger

logger = get_logger(__name__)

EXPORT_URL = "https://deals.grabcash.in/api/v1/export/deals"

# Field names verified against the live GrabCash API response
# (https://deals.grabcash.in/api/v1/deals). Aliases kept for resilience.
_FIELD_ALIASES = {
    "title": ["product_title", "caption", "title", "name", "product_name"],
    "url": ["original_url", "url", "link", "deal_url", "product_url"],
    "merchant_url": ["merchant_url", "store_url", "source_url"],
    "image": ["image_url", "image", "img", "thumbnail"],
    "scraped_price": list(PRICE_FIELD_ALIASES),
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


class DealSourceClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base = os.environ.get("DEAL_API_BASE") or self.settings.grabcash_api_base
        self.key = self.settings.api_secret_key
        self.auth = os.environ.get("DEAL_API_AUTH", "bearer")
        self.source = os.environ.get("DEAL_API_SOURCE", "deal_api")

    def available(self) -> tuple[bool, str | None]:
        if not self.key:
            return False, "Deal source not configured. Set API_SECRET_KEY in .env."
        return True, None

    def _fetch_retailer_httpx(self, retailer: str, want: int, page_size: int) -> list[dict]:
        """One retailer's pool from the GrabCash export API (fast path). Auth is the
        `key` query param — NOT the header/bearer scheme the old /deals endpoint used.
        Paginates using the response's `total` vs items collected so far. Raises on
        Cloudflare 403 / network error."""
        collected: list[dict] = []
        page = 1
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            while len(collected) < want:
                params = {"key": self.key, "retailer": retailer,
                          "page_size": page_size, "page": page}
                resp = client.get(EXPORT_URL, params=params)
                resp.raise_for_status()
                payload = resp.json()
                items = payload.get("items") or []
                if not items:
                    break
                collected.extend(items)
                if len(collected) >= (payload.get("total") or 0):
                    break
                page += 1
        return collected[:want]

    def _collect_raw(self, want: int, page_size: int) -> list[dict]:
        """Raw deal dicts via the export API, queried once per allowed retailer and
        merged, falling back to the Camoufox stealth browser when Cloudflare blocks
        the plain client (403) or the export calls fail outright."""
        per_retailer_want = max(-(-want // len(ALLOWED_MERCHANTS)), 1)  # ceil division
        try:
            collected: list[dict] = []
            for retailer in sorted(ALLOWED_MERCHANTS):
                items = self._fetch_retailer_httpx(retailer, per_retailer_want, page_size)
                logger.info("[deal_source] fetched %d items for retailer=%s via export API",
                            len(items), retailer)
                collected.extend(items)
            if collected:
                return collected
            logger.warning("[deal_source] export API returned no items for any retailer; "
                            "trying browser")
        except httpx.HTTPStatusError as e:
            # Log the ACTUAL failure, not just str(e): status, whether Cloudflare's
            # edge WAF blocked us (common — the request never reaches the app, so the
            # API key is irrelevant), and a short body snippet. Then fall back.
            resp = e.response
            body = " ".join((resp.text or "")[:300].split())
            is_cf = "cloudflare" in resp.headers.get("server", "").lower()
            blocked = is_cf and ("Attention Required" in resp.text
                                 or "you have been blocked" in resp.text)
            logger.warning(
                "[deal_source] direct API HTTP %s at %s%s (cf-ray=%s); body[:300]=%r; "
                "falling back to Camoufox browser",
                resp.status_code, e.request.url,
                " - Cloudflare bot-block (edge WAF, request never reached the app; "
                "API key is not the issue)" if blocked else "",
                resp.headers.get("cf-ray", "-"), body,
            )
        except Exception as e:  # network / schema / other
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
