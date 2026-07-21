"""Provider selection — maps an org's configured provider name to an instance.

Resolution order: the Organization's ``settings`` (per-tenant) first, then .env
defaults. This is the ONLY place that knows provider names — the core calls
``get_affiliate_provider(org)`` and receives an ``AffiliateProvider``; it never
branches on 'grabon' itself.
"""

from __future__ import annotations

from types import SimpleNamespace

from src.services.affiliate.base import AffiliateProvider
from src.services.affiliate.generic import GenericAffiliateProvider


def _settings_for_org(org) -> SimpleNamespace | None:
    """Build a settings-shaped object from an Organization's stored settings."""
    if org is None or not org.settings:
        return None
    s = org.settings
    prov = (org.affiliate_provider or s.get("affiliate_provider") or "generic").lower()
    return SimpleNamespace(
        affiliate_provider_name=prov,
        grabon_shortener_url=s.get("grabon_shortener_url"),
        grabon_amazon_tag=s.get("grabon_amazon_tag"),
        grabon_flipkart_params=s.get("grabon_flipkart_params"),
        grabon_myntra_deeplink=s.get("grabon_myntra_deeplink"),
        grabon_shorten_all=s.get("grabon_shorten_all", True),
    )


def get_affiliate_provider(org=None, settings=None) -> AffiliateProvider:
    """Resolve the provider for an org (preferred) or from global settings/.env."""
    resolved = _settings_for_org(org)
    if resolved is None:
        from src.config.settings import get_settings
        resolved = settings or get_settings()

    name = resolved.affiliate_provider_name
    if name == "grabon":
        from src.services.affiliate.grabon import GrabOnAffiliateProvider
        return GrabOnAffiliateProvider(resolved)
    return GenericAffiliateProvider()
