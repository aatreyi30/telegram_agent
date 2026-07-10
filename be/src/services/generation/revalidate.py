"""Pre-publish revalidation (Phase 0.3) — the last honesty gate before a draft
goes out. A queued post can sit for a while before an operator (or, later, the
auto-publisher) sends it; by then a product may have sold out, its price may
have moved, or the link may be dead. This module re-checks every deal a post
carries right before publish, so a stale/broken deal can never go out silently.

For merchants we can actually scrape (see ``SCRAPEABLE_MERCHANTS``, mirroring
the sources wired in ``src.services.collection.merchant``), a stale product is
refreshed synchronously via ``MerchantEnrichmentCollector``. For everyone else
(BLOCKED/unknown merchants — ajio, nykaa, croma, zepto, blinkit, ...) we can
only confirm the link still resolves; price/stock there were never
collectable in the first place (never fabricated).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from src.db.models import MerchantProduct
from src.db.models_generation import EnrichedDeal
from src.db.session import session_scope
from src.logger import get_logger

logger = get_logger(__name__)

# Merchants with an implemented MerchantSource (mirrors
# src.services.collection.merchant._SOURCES) — everyone else is BLOCKED/unknown
# and gets a liveness-only check.
SCRAPEABLE_MERCHANTS = {"boat", "reliance_digital", "amazon", "flipkart"}

MAX_PRICE_RISE_PCT = 0.10   # >10% price rise vs. the deal's stored price -> blocked
_HTTP_TIMEOUT_SECONDS = 8.0


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; we always store UTC, so treat naive as UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _http_ok(url: str) -> tuple[bool, str | None]:
    """Liveness check only — no price/stock signal available here."""
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS, follow_redirects=True) as c:
            r = c.head(url)
            if r.status_code >= 400 and r.status_code not in (403, 405, 429):
                r = c.get(url)  # some merchants reject HEAD but serve GET
            if r.status_code >= 400:
                return False, f"dead link ({r.status_code})"
            return True, None
    except Exception as e:  # noqa: BLE001 - network is inherently unreliable
        return False, f"unreachable ({type(e).__name__})"


def _check_product(product: MerchantProduct, deal: EnrichedDeal) -> dict:
    """Verdict from an already-fresh (or just-refreshed) MerchantProduct row."""
    if product.availability and product.availability.lower() not in ("in_stock", "unknown"):
        return {"ok": False, "reason": f"out of stock ({product.availability})"}
    if product.current_price is not None and deal.current_price:
        if product.current_price > deal.current_price * (1 + MAX_PRICE_RISE_PCT):
            pct = (product.current_price / deal.current_price - 1) * 100
            return {"ok": False,
                    "reason": f"price risen {pct:.0f}% ({deal.current_price} -> {product.current_price})"}
    return {"ok": True, "reason": None}


def _refresh_product(url: str) -> MerchantProduct | None:
    """Synchronously re-scrape a scrapeable merchant's product page."""
    from src.db.models import CollectionType
    from src.services.collection.base import JobRunner
    from src.services.collection.merchant import MerchantEnrichmentCollector

    JobRunner().run_collector(
        MerchantEnrichmentCollector(url),
        collection_type=CollectionType.MANUAL,
        target="prepublish_revalidate",
    )
    with session_scope() as s:
        product = s.scalar(select(MerchantProduct).where(MerchantProduct.product_url == url))
        if product is not None:
            s.expunge(product)
        return product


def _revalidate_one(deal: EnrichedDeal, max_staleness_min: int) -> dict:
    """Return ``{"ok": bool, "reason": str | None}`` for a single deal."""
    url = deal.clean_url or deal.url
    if not url:
        return {"ok": False, "reason": f"deal {deal.deal_id} has no URL"}

    stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_staleness_min)
    with session_scope() as s:
        product = s.scalar(select(MerchantProduct).where(MerchantProduct.product_url == url))
        if product is not None:
            s.expunge(product)

    verified_at = _aware(product.last_verified_at) if product else None
    fresh = bool(verified_at and verified_at >= stale_cutoff)
    if fresh:
        return _check_product(product, deal)

    if deal.merchant_key in SCRAPEABLE_MERCHANTS:
        product = _refresh_product(url)
        if product is None:
            # source unavailable / product not found (e.g. delisted) -> liveness check
            ok, reason = _http_ok(url)
            return {"ok": ok, "reason": reason}
        return _check_product(product, deal)

    # BLOCKED/unknown merchant — price/stock were never collectable; confirm the
    # link still resolves, which is the whole of what we can honestly check.
    ok, reason = _http_ok(url)
    return {"ok": ok, "reason": reason}


def revalidate_deals(deal_ids: list[str], *, max_staleness_min: int) -> dict:
    """Revalidate every deal a post carries before it publishes.

    ``deal_ids`` are ``EnrichedDeal.deal_id`` (content-hash) values, exactly what
    ``GeneratedPost.deal_ids`` stores. Returns the first failing verdict, or
    ``{"ok": True}`` once every deal has been confirmed fresh.
    """
    if not deal_ids:
        return {"ok": True, "reason": None}

    with session_scope() as s:
        deals = s.scalars(select(EnrichedDeal).where(EnrichedDeal.deal_id.in_(deal_ids))).all()
        s.expunge_all()

    found_ids = {d.deal_id for d in deals}
    for missing in set(deal_ids) - found_ids:
        return {"ok": False, "reason": f"deal {missing} no longer exists"}

    for deal in deals:
        verdict = _revalidate_one(deal, max_staleness_min)
        if not verdict["ok"]:
            logger.info("[prepublish_revalidate] deal %s BLOCKED: %s", deal.deal_id, verdict["reason"])
            return verdict
    return {"ok": True, "reason": None}
