"""Camoufox browser-based deal fetch + relevance filter.

The GrabCash deals API sits behind Cloudflare, which 403s a plain HTTP client
(datacenter/bot fingerprint). A real stealth browser (Camoufox) loads the site,
clears the Cloudflare challenge, and then calls the API from the page context
(carrying the clearance cookie) — which returns the deals JSON.

Relevance is applied here so ONLY attractive-to-customers deals flow downstream:
a genuine saving (price < mrp), a real merchant + product URL, a strong discount,
and a high deal_score. Results are ranked most-attractive first.
"""

from __future__ import annotations

import json
import os
from urllib.parse import urlparse

from src.config.settings import get_settings
from src.logger import get_logger

logger = get_logger(__name__)

# "attractive to a customer" thresholds (tunable)
MIN_DEAL_SCORE = 70
MIN_DISCOUNT = 40

# Merchants we're actually allowed to post right now. The GrabCash feed carries many
# more retailers (Nykaa, TataCliq, Shopsy, ...) than we have a real posting
# relationship with -- restrict here, at the single shared relevance gate, so every
# consumer of filter_relevant() (jit_fill, DealSourceClient.fetch_latest) is
# automatically limited to the same allow-list instead of drifting independently.
ALLOWED_MERCHANTS = {"amazon", "flipkart", "myntra", "ajio"}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def is_relevant(it: dict) -> bool:
    """A deal worth posting: real product + merchant (from the allow-list), a
    genuine saving, strong discount and deal score."""
    if not (it.get("product_title") and it.get("original_url") and it.get("retailer_key")):
        return False
    if str(it["retailer_key"]).lower() not in ALLOWED_MERCHANTS:
        return False
    mrp, price = _num(it.get("mrp")), _num(it.get("discount_price"))
    disc, score = _num(it.get("discount_percentage")) or 0, _num(it.get("deal_score")) or 0
    if not mrp or not price or not (0 < price < mrp):
        return False
    return disc >= MIN_DISCOUNT and score >= MIN_DEAL_SCORE


def _relevance_key(it: dict):
    # most attractive first: deal_score then discount %
    return (_num(it.get("deal_score")) or 0, _num(it.get("discount_percentage")) or 0)


def filter_relevant(items: list[dict]) -> list[dict]:
    """Keep only attractive deals, ranked most-attractive first. Dedupes by URL."""
    seen, out = set(), []
    for it in sorted(items, key=_relevance_key, reverse=True):
        url = it.get("original_url")
        if not is_relevant(it) or url in seen:
            continue
        seen.add(url)
        out.append(it)
    return out


def diversify_by_category(relevant: list[dict], limit: int, max_per_category: int = 6) -> list[dict]:
    """Spread the pick across categories so posts have variety (the API sorts by
    deal_score globally, which front-loads one category). Categories are ordered by
    their best deal; within a category the most attractive deals come first; we
    round-robin across categories up to `max_per_category` each, until `limit`.

    Keeps only attractiveness — every returned deal already passed is_relevant."""
    buckets: dict[str, list[dict]] = {}
    for it in relevant:  # relevant is already sorted most-attractive first
        buckets.setdefault(it.get("category_key") or "other", []).append(it)
    # order categories by their strongest deal
    cats = sorted(buckets, key=lambda c: _relevance_key(buckets[c][0]), reverse=True)
    out, idx = [], 0
    while len(out) < limit and any(buckets.values()):
        cat = cats[idx % len(cats)]
        idx += 1
        taken = sum(1 for d in out if (d.get("category_key") or "other") == cat)
        if buckets[cat] and taken < max_per_category:
            out.append(buckets[cat].pop(0))
        if idx % len(cats) == 0 and not any(
                b and sum(1 for d in out if (d.get("category_key") or "other") == c) < max_per_category
                for c, b in buckets.items()):
            break
    return out


def _site_root(api_url: str) -> str:
    p = urlparse(api_url)
    return f"{p.scheme}://{p.netloc}/"


class CamoufoxDealSource:
    """Fetch raw deal dicts through a stealth browser (Cloudflare-bypassing)."""

    def __init__(self) -> None:
        s = get_settings()
        self.api_url = os.environ.get("DEAL_API_BASE") or s.grabcash_api_base
        self.key = s.api_secret_key
        auth = os.environ.get("DEAL_API_AUTH", "bearer")
        self.header_name = auth.split(":", 1)[1] if auth.startswith("header:") else "X-API-Key"
        self.site = _site_root(self.api_url) if self.api_url else None

    def fetch_raw(self, want: int = 60, page_size: int = 60, max_pages: int = 6) -> list[dict]:
        """Load the site (CF clearance) then page the API from the page context."""
        from camoufox.sync_api import Camoufox  # heavy import kept local

        collected: list[dict] = []
        with Camoufox(headless=True, os="windows") as browser:
            ctx = browser.new_context(no_viewport=True)  # avoids the viewport protocol quirk
            page = ctx.new_page()
            page.goto(self.site, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(3500)  # let the Cloudflare challenge settle
            pg = 1
            while len(collected) < want and pg <= max_pages:
                res = page.evaluate(
                    """async ({url, hname, key, pg, ps}) => {
                        const u = new URL(url);
                        u.searchParams.set('page', pg);
                        u.searchParams.set('page_size', ps);
                        const h = {}; if (hname && key) h[hname] = key;
                        const r = await fetch(u.toString(), { headers: h });
                        return { status: r.status, body: await r.text() };
                    }""",
                    {"url": self.api_url, "hname": self.header_name, "key": self.key,
                     "pg": pg, "ps": page_size},
                )
                if res["status"] != 200:
                    logger.warning("[camoufox] deals API returned %s on page %d", res["status"], pg)
                    break
                try:
                    data = json.loads(res["body"])
                except ValueError:
                    logger.warning("[camoufox] non-JSON body on page %d", pg)
                    break
                items = data.get("items") or []
                if not items:
                    break
                collected.extend(items)
                pages = data.get("pages")
                if pages and pg >= pages:
                    break
                pg += 1
        logger.info("[camoufox] collected %d raw deal(s) across pages", len(collected))
        return collected
