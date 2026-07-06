"""Generic pass-through provider — the default when no org-specific provider is set.

It performs no affiliate transformation (the platform has no universal affiliate
network), so ``final_url`` is the clean product URL. This is the honest baseline:
posting still works; the link simply carries no tracking until a real provider
(GrabOn, Amazon Creator API, …) is configured.
"""

from __future__ import annotations

from src.services.affiliate.base import AffiliateProvider, AffiliateResult


class GenericAffiliateProvider(AffiliateProvider):
    name = "generic"

    def generate(self, product_url: str, merchant_key: str | None = None) -> AffiliateResult:
        return AffiliateResult(
            original_url=product_url,
            merchant_key=merchant_key,
            affiliate_url=None,
            short_url=None,
            provider=self.name,
            shortened=False,
            notes=["No affiliate provider configured — using clean product URL (untracked)."],
        )
