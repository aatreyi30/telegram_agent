"""Merchant source interface + the product-data value object."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProductData:
    """Normalised product facts fetched from a merchant source.

    Every field defaults to None ("unknown") — a source only fills what it can
    actually observe. Missing values are never invented (RULE 1).
    """

    external_id: str
    product_url: str | None = None
    title: str | None = None
    brand: str | None = None
    category_text: str | None = None
    image_url: str | None = None
    current_price: float | None = None
    mrp: float | None = None
    currency: str = "INR"
    availability: str | None = None
    raw_payload: Any = None


class MerchantSource:
    """A source that can fetch product data for one merchant."""

    #: merchant registry key this source populates
    merchant_key: str = "base"

    def available(self) -> tuple[bool, str | None]:
        """Whether this source can run (creds present, contract verified, ...)."""
        return True, None

    def matches(self, url: str) -> bool:
        raise NotImplementedError

    def fetch(self, url: str) -> ProductData | None:
        """Return ProductData, or None if the product could not be fetched.

        Raise on transient errors so the JobRunner can retry.
        """
        raise NotImplementedError
