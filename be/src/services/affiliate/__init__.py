"""Affiliate link generation — a multi-provider, org-selected layer.

The core platform stays provider-agnostic: it asks the configured
``AffiliateProvider`` to turn a product URL into a tracked/short link and uses
whatever comes back. GrabOn's client-specific rules + shortener live entirely in
``grabon.GrabOnAffiliateProvider`` and are activated only when the org configures
``AFFILIATE_PROVIDER=grabon`` — no GrabOn logic exists in the core (per the spec).
"""

from src.services.affiliate.base import AffiliateProvider, AffiliateResult
from src.services.affiliate.registry import get_affiliate_provider

__all__ = ["AffiliateProvider", "AffiliateResult", "get_affiliate_provider"]
