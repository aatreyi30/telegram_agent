"""boAt merchant source — Shopify storefront JSON (public, no credentials).

Shopify stores expose ``/products/<handle>.json`` by default (confirmed in
research). This is a fully-implemented, verified source.
"""

from __future__ import annotations

import re

import httpx

from src.services.collection.merchants.base import MerchantSource, ProductData

_HANDLE_RE = re.compile(r"/products/([^/?#]+)")


class BoatShopifySource(MerchantSource):
    merchant_key = "boat"

    def matches(self, url: str) -> bool:
        u = url.lower()
        return "boat-lifestyle.com" in u or "boatlifestyle.com" in u

    def fetch(self, url: str) -> ProductData | None:
        m = _HANDLE_RE.search(url)
        if not m:
            return None
        handle = m.group(1)
        base = url.split("/products/")[0]
        json_url = f"{base}/products/{handle}.json"

        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(json_url)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()

        product = data.get("product") or {}
        variants = product.get("variants") or []
        first = variants[0] if variants else {}
        images = product.get("images") or []

        def _to_float(v):
            try:
                return float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                return None

        available = None
        if variants:
            available = "in_stock" if any(v.get("available") for v in variants) else "out_of_stock"

        return ProductData(
            external_id=str(product.get("id") or handle),
            product_url=url,
            title=product.get("title"),
            brand=product.get("vendor"),
            category_text=product.get("product_type"),
            image_url=(images[0].get("src") if images else None),
            current_price=_to_float(first.get("price")),
            mrp=_to_float(first.get("compare_at_price")),
            currency="INR",
            availability=available,
            raw_payload=data,
        )
