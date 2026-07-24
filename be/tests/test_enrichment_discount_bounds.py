"""Enrichment must reject corrupt SOURCE discounts.

A 100% ("free") or negative discount from the deal feed is bad data, not a real
deal — the old code trusted rd.discount unbounded, so 1 deal at 100% and 14 at
>=90% persisted as top-ranked "loot". `_pre_parse` now rejects anything outside
[0, 100) and only price-derives when current > 0.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.services.generation.enrichment import DealEnrichmentEngine, RawDeal


def _engine():
    sess = MagicMock()
    sess.scalars.return_value = []          # no merchants -> _access = {}
    return DealEnrichmentEngine(sess)


@pytest.mark.parametrize("bad", ["100", "150"])
def test_implausible_source_discount_rejected(bad):
    eng = _engine()
    # current=0 (a "free" row) -> cannot price-derive either -> None
    p = eng._pre_parse(RawDeal(url="https://amazon.in/p", scraped_price="0",
                               scraped_mrp="1000", discount=bad, merchant_key="amazon"))
    assert p["discount_percent"] is None


def test_legit_source_discount_kept():
    eng = _engine()
    p = eng._pre_parse(RawDeal(url="https://amazon.in/p", scraped_price="400",
                               scraped_mrp="1000", discount="60", merchant_key="amazon"))
    assert p["discount_percent"] == 60


def test_price_derivation_never_yields_100(eng_scope=None):
    """current>0 guard: a real discounted price derives a sane <100 discount."""
    eng = _engine()
    p = eng._pre_parse(RawDeal(url="https://amazon.in/p", scraped_price="250",
                               scraped_mrp="1000", merchant_key="amazon"))
    assert p["discount_percent"] == 75.0
