"""The provider-agnostic affiliate interface.

Every provider takes a product URL (+ optional known merchant) and returns an
``AffiliateResult``. The core reads ``final_url`` and never needs to know which
provider produced it. This keeps the platform multi-tenant: new providers
(Amazon Creator API, other networks, manual links) implement the same interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AffiliateResult:
    original_url: str                       # what came in (raw merchant URL)
    merchant_key: str | None                # detected/known merchant, or None
    affiliate_url: str | None               # provider deep link, before shortening
    short_url: str | None                   # shortener output, if any
    provider: str                           # provider name that produced this
    shortened: bool                         # True only if a real short link came back
    notes: list[str] = field(default_factory=list)

    @property
    def final_url(self) -> str:
        """The link to actually put in a post.

        Fallback chain (never blocks posting): short URL → affiliate URL →
        original URL. Matches the spec: 'If shortening fails, fall back to the
        generated affiliate URL so posting is never blocked.'
        """
        return self.short_url or self.affiliate_url or self.original_url


class AffiliateProvider(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, product_url: str, merchant_key: str | None = None) -> AffiliateResult:
        """Turn a product URL into an affiliate link (and short link if supported)."""
        raise NotImplementedError
