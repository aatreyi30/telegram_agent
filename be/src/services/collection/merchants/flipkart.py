"""Flipkart merchant source — Affiliate API.

STATUS: credential-gated + request-contract-unverified (same policy as Amazon).

Research confirms the Flipkart Affiliate API exists (product catalog + pricing)
but rate limits are unconfirmed and the request contract is not verified in
code. Per RULE 1 / RULE 5 this source stays unavailable with a precise reason
until ``_call_api`` is implemented against verified docs — it never fabricates
requests or product data.
"""

from __future__ import annotations

import re

from src.services.collection.merchants.base import MerchantSource, ProductData
from src.config.settings import get_settings

_FSN_RE = re.compile(r"/p/(itm[a-z0-9]+)", re.IGNORECASE)


class FlipkartAffiliateSource(MerchantSource):
    merchant_key = "flipkart"

    def __init__(self) -> None:
        self.settings = get_settings()

    def available(self) -> tuple[bool, str | None]:
        if not self.settings.flipkart_available:
            return False, "Flipkart Affiliate API credentials not configured."
        return (
            False,
            "Flipkart Affiliate API request contract unverified — implement "
            "_call_api against current docs before enabling (RULE 5).",
        )

    def matches(self, url: str) -> bool:
        u = url.lower()
        return "flipkart.com" in u or "fkrt.cc" in u or "fkrt.it" in u

    def fetch(self, url: str) -> ProductData | None:  # pragma: no cover
        raise NotImplementedError(
            "Flipkart Affiliate API call not implemented — see module docstring."
        )
