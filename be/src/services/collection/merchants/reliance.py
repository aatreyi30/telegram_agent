"""Reliance Digital source — HTTP fetch with honest partial parsing.

Research rates Reliance Digital as MEDIUM confidence: low robots.txt
protection, but the page is JS-heavy so structured fields are not reliably
present in the initial HTML. Per RULE 1 (no hallucination) this source stores
the raw page for traceability and only fills structured fields it can extract
with confidence (currently: none verified). It never invents price/title.

To enable structured extraction, verify the page's selectors / embedded JSON
and implement ``_parse`` — until then this returns a ProductData with the URL
and everything else UNKNOWN.
"""

from __future__ import annotations

import httpx

from src.config.settings import get_settings
from src.services.collection.merchants.base import MerchantSource, ProductData


class RelianceDigitalSource(MerchantSource):
    merchant_key = "reliance_digital"

    def available(self) -> tuple[bool, str | None]:
        # Fetch works; structured extraction is unverified. We stay available so
        # the raw snapshot is captured, but return only observed facts.
        return True, None

    def matches(self, url: str) -> bool:
        return "reliancedigital.in" in url.lower()

    def fetch(self, url: str) -> ProductData | None:
        with httpx.Client(
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": get_settings().tme_user_agent},
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text

        # No verified selectors yet -> do not guess. Return URL + raw only.
        return ProductData(
            external_id=url.rstrip("/").split("/")[-1],
            product_url=url,
            raw_payload=html,
        )
