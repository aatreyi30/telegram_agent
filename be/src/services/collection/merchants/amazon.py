"""Amazon merchant source — Creators API (replaced PA-API on 2026-05-15).

STATUS: credential-gated + request-contract-unverified.

Research confirms the API EXISTS and the access method (REST + affiliate
credentials), but the exact request signing/endpoint schema for the Creators
API is only partially documented. Per RULE 1 (no hallucination) and RULE 5
(stop if uncertain), this source does NOT ship a guessed signing implementation
that would fabricate requests. It reports itself unavailable with a precise
reason until the request contract is verified against the current docs and
wired into ``_call_api``.

When you implement ``_call_api``: extract the ASIN from the URL, call the
Creators API GetItems-equivalent endpoint, and map the response into
ProductData. Do not invent field names — copy them from the verified response.
"""

from __future__ import annotations

import re

from src.services.collection.merchants.base import MerchantSource, ProductData
from src.config.settings import get_settings

_ASIN_RE = re.compile(r"/(?:dp|gp/product|d)/([A-Z0-9]{10})", re.IGNORECASE)


class AmazonCreatorsSource(MerchantSource):
    merchant_key = "amazon"

    def __init__(self) -> None:
        self.settings = get_settings()

    def available(self) -> tuple[bool, str | None]:
        if not self.settings.amazon_available:
            return False, "Amazon Creators API credentials not configured."
        # Credentials present, but the request contract is not verified in code.
        return (
            False,
            "Amazon Creators API request contract unverified — implement "
            "_call_api against current docs before enabling (RULE 5).",
        )

    def matches(self, url: str) -> bool:
        u = url.lower()
        return "amazon.in" in u or "amzn.to" in u or "amzn.in" in u

    @staticmethod
    def extract_asin(url: str) -> str | None:
        m = _ASIN_RE.search(url)
        return m.group(1).upper() if m else None

    def fetch(self, url: str) -> ProductData | None:  # pragma: no cover
        raise NotImplementedError(
            "Amazon Creators API call not implemented — see module docstring."
        )
