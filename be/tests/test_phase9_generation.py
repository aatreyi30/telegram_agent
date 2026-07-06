"""Phase 9 tests — enrichment parsing, loot detection, selection diversity."""

from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/gen.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.services.collection.merchants.registry import seed_merchants
    from src.db.session import init_db, session_scope

    init_db()
    with session_scope() as s:
        seed_merchants(s)
    yield


def test_to_float_and_clean_url():
    from src.services.generation.enrichment import _clean_url, _to_float

    assert _to_float("₹1,299") == 1299.0
    assert _to_float("999") == 999.0
    assert _to_float(None) is None
    assert _to_float("") is None
    # tracking params stripped, real path/query kept
    cleaned = _clean_url("https://www.amazon.in/dp/B01?tag=aff-21&th=1&utm_source=tg")
    assert "tag=" not in cleaned and "utm_source=" not in cleaned
    assert "th=1" in cleaned and "/dp/B01" in cleaned


def test_enrichment_data_derived_loot_and_validity():
    from src.db.session import session_scope
    from src.services.generation.enrichment import DealEnrichmentEngine, RawDeal

    raw = [
        RawDeal(title="a", url="https://www.amazon.in/dp/B1", scraped_price="900", scraped_mrp="1000"),   # 10%
        RawDeal(title="b", url="https://www.amazon.in/dp/B2", scraped_price="700", scraped_mrp="1000"),   # 30%
        RawDeal(title="c", url="https://www.amazon.in/dp/B3", scraped_price="500", scraped_mrp="1000"),   # 50%
        RawDeal(title="d", url="https://www.amazon.in/dp/B4", scraped_price="100", scraped_mrp="1000"),   # 90% -> loot
        RawDeal(title="e", url="https://www.flipkart.com/p/itm9", scraped_price="1200", scraped_mrp="1000"),  # invalid
    ]
    with session_scope() as s:
        deals = DealEnrichmentEngine(s).enrich_batch(raw)
    by_title = {d.title: d for d in deals}
    # merchant detected from URL, never fabricated
    assert by_title["a"].merchant_key == "amazon"
    assert by_title["e"].merchant_key == "flipkart"
    # discount derived from prices
    assert by_title["c"].discount_percent == 50.0
    # loot is the top-quartile discount within the batch (data-derived), not hardcoded
    assert by_title["d"].is_loot_deal is True
    assert by_title["a"].is_loot_deal is False
    # current > mrp -> invalid, never assumed valid
    assert by_title["e"].deal_validity == "invalid"
    # affiliate link deferred -> never fabricated
    assert all(d.affiliate_link is None for d in deals)


def test_selection_is_diverse_across_buckets():
    from src.services.generation.ranking import DealSelector

    def deal(loot, price, merchant, score):
        return SimpleNamespace(is_loot_deal=loot, current_price=price, merchant_key=merchant,
                               deal_validity="valid", rank_score=score, deal_id=str(score))

    ranked = [
        deal(True, 150, "amazon", 30),     # loot + budget
        deal(False, 40000, "flipkart", 25),  # high-value
        deal(False, 300, "boat", 20),        # budget
        deal(False, 1500, "reliance_digital", 15),  # mid -> exploration/trending
        deal(False, 1200, "amazon", 10),     # mid, repeat merchant
    ]
    chosen = DealSelector().select(ranked, count=5)
    buckets = {b for _, b in chosen}
    assert len(chosen) == 5
    # spans multiple distinct buckets (not all the same)
    assert len(buckets) >= 3


def test_deal_source_maps_grabcash_schema():
    from src.services.generation.deal_source import _extract_items, _map_item

    payload = {"items": [{
        "id": "deal_abc", "product_title": "Puma Walking Shoes", "original_url": "https://www.ajio.com/p/469763551001",
        "retailer_key": "ajio", "discount_price": 2369.0, "mrp": 5999.0, "discount_percentage": 61,
        "category_key": "fashion-and-lifestyle", "subcategory_key": "shoes", "deal_score": 96,
        "coupon_code": None, "ingested_at": "2026-07-02T20:09:01Z",
    }], "total": 1, "pages": 1}
    items = _extract_items(payload)
    assert len(items) == 1
    rd = _map_item(items[0], "grabcash_api")
    assert rd.title == "Puma Walking Shoes"
    assert rd.url == "https://www.ajio.com/p/469763551001"
    assert rd.merchant_key == "ajio"           # merchant given directly, not URL-guessed
    assert rd.category == "fashion-and-lifestyle"
    assert float(rd.scraped_price) == 2369.0
    assert float(rd.scraped_mrp) == 5999.0
    assert rd.external_id == "deal_abc"


def test_source_provided_merchant_wins_and_category_flows_through():
    from src.db.session import session_scope
    from src.services.generation.enrichment import DealEnrichmentEngine, RawDeal

    rd = RawDeal(title="Puma", url="https://www.ajio.com/p/1", merchant_key="ajio",
                 category="fashion-and-lifestyle", scraped_price="2369", scraped_mrp="5999",
                 discount="61", source="grabcash_api")
    with session_scope() as s:
        deal = DealEnrichmentEngine(s).enrich_batch([rd])[0]
    assert deal.merchant_key == "ajio"               # source-provided, authoritative
    assert deal.category == "fashion-and-lifestyle"  # real category flows through
    assert deal.deal_validity == "valid"
    # source provided structured data -> confidence not penalised for AJIO being scrape-blocked
    assert deal.price_confidence_score >= 0.8


def test_parse_items_extracts_name_and_real_link_pairs():
    from src.services.generation.candidates import _parse_items

    text = ("Kids Loot Under ₹100 ✨😍\n\n"
            "Cartoon Eraser Set - https://grbn.in/gBtgIK\n"
            "Crayons - https://grbn.in/yo315t\n\n"
            "Shop Now")
    items = _parse_items(text)
    assert len(items) == 2
    assert items[0].name == "Cartoon Eraser Set"
    assert items[0].url == "https://grbn.in/gBtgIK"
    # the theme line and CTA line are not mistaken for products
    assert all(i.url.startswith("https://grbn.in/") for i in items)


def test_selection_excludes_invalid_deals():
    from src.services.generation.ranking import DealSelector

    invalid = SimpleNamespace(is_loot_deal=False, current_price=100, merchant_key="amazon",
                              deal_validity="invalid", rank_score=99, deal_id="x")
    valid = SimpleNamespace(is_loot_deal=False, current_price=100, merchant_key="amazon",
                            deal_validity="valid", rank_score=1, deal_id="y")
    chosen = DealSelector().select([invalid, valid], count=5)
    assert all(d.deal_validity == "valid" for d, _ in chosen)
