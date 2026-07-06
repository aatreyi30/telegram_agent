"""Phase-1 unit tests for the deterministic pieces (no network required).

Covers the rules most at risk of silent regression:
  * abbreviated-count parsing (never guesses -> None on failure)
  * merchant detection by domain + BLOCKED-merchant representation
  * URL extraction is pure observation
  * storage layer round-trips + raw-snapshot dedup by content hash
"""

from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    # reset cached settings/engine so the env above takes effect
    from src.config.settings import get_settings
    from src.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db

    init_db()
    yield


def test_parse_abbreviated_int():
    from src.services.collection.util import parse_abbreviated_int

    assert parse_abbreviated_int("3.4M") == 3_400_000
    assert parse_abbreviated_int("12.3K") == 12_300
    assert parse_abbreviated_int("1,234") == 1_234
    assert parse_abbreviated_int("987") == 987
    # never guesses
    assert parse_abbreviated_int(None) is None
    assert parse_abbreviated_int("") is None


def test_extract_urls_is_pure_observation():
    from src.services.collection.util import extract_urls

    text = "Deal https://amzn.to/abc and https://flipkart.com/p/itm123 now!"
    urls = extract_urls(text)
    assert "https://amzn.to/abc" in urls
    assert "https://flipkart.com/p/itm123" in urls
    assert extract_urls(None) == []


def test_merchant_detection_and_blocked_representation():
    from src.services.collection.merchants.registry import detect_merchant_key, seed_merchants
    from src.db.models import Merchant, SourceAccessStatus
    from src.db.session import session_scope
    from sqlalchemy import select

    with session_scope() as s:
        seed_merchants(s)

    assert detect_merchant_key("https://www.amazon.in/dp/B0ABC12345") == "amazon"
    assert detect_merchant_key("https://www.ajio.com/p/x") == "ajio"
    assert detect_merchant_key("https://unknown-shop.example/x") is None

    with session_scope() as s:
        ajio = s.scalar(select(Merchant).where(Merchant.key == "ajio"))
        assert ajio.access_status == SourceAccessStatus.BLOCKED
        assert ajio.collector is None  # BLOCKED merchants have NO collector
        boat = s.scalar(select(Merchant).where(Merchant.key == "boat"))
        assert boat.access_status == SourceAccessStatus.AVAILABLE


def test_amazon_asin_extraction():
    from src.services.collection.merchants.amazon import AmazonCreatorsSource

    assert AmazonCreatorsSource.extract_asin("https://www.amazon.in/dp/B0ABC12345") == "B0ABC12345"
    assert AmazonCreatorsSource.extract_asin("https://www.amazon.in/gp/product/B0XYZ98765/") == "B0XYZ98765"
    assert AmazonCreatorsSource.extract_asin("https://www.amazon.in/no-asin-here") is None


def test_raw_snapshot_dedup_by_content_hash():
    from src.services.collection.raw_store import store_raw
    from src.db.session import session_scope

    with session_scope() as s:
        a = store_raw(s, source="test", source_ref="r1", payload={"x": 1})
        b = store_raw(s, source="test", source_ref="r1", payload={"x": 1})
        c = store_raw(s, source="test", source_ref="r1", payload={"x": 2})
    assert a.id == b.id          # identical content -> same snapshot (deduped)
    assert c.id != a.id          # different content -> new snapshot
    assert a.content_sha256 != c.content_sha256


def test_blocked_merchant_collector_skips_without_fetch():
    from src.services.collection.merchant import MerchantEnrichmentCollector

    collector = MerchantEnrichmentCollector("https://www.zeptonow.com/p/some-item")
    ok, reason = collector.available()
    assert ok is False
    assert "BLOCKED" in reason
