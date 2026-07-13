"""Phase 0.3 tests — pre-publish revalidation blocks stale/dead/repriced deals
before a post is allowed to publish (never send a dead deal silently)."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone

import pytest
from sqlalchemy import select


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/revalidate.db"
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


def _make_deal(s, deal_id: str, merchant_key: str, url: str, current_price: float = 1000.0):
    from src.db.models_generation import DealValidity, EnrichedDeal

    d = EnrichedDeal(deal_id=deal_id, source="manual", title="t", url=url, clean_url=url,
                     merchant_key=merchant_key, current_price=current_price,
                     deal_validity=DealValidity.VALID)
    s.add(d)
    s.flush()
    return d


def test_dead_link_blocks_non_scrapeable_merchant(monkeypatch):
    """ajio/nykaa/etc are BLOCKED merchants — never scraped, only a liveness
    check is possible. A dead link (404) must block the deal."""
    from src.db.session import session_scope
    from src.services.generation import revalidate

    with session_scope() as s:
        _make_deal(s, "deal-404", "ajio", "https://www.ajio.com/p/gone")

    monkeypatch.setattr(revalidate, "_http_ok", lambda url: (False, "dead link (404)"))
    verdict = revalidate.revalidate_deals(["deal-404"], max_staleness_min=30)
    assert verdict["ok"] is False
    assert "404" in verdict["reason"]


def test_price_risen_blocks_scrapeable_merchant():
    """A fresh (just-verified) MerchantProduct whose price rose >10% vs. the
    deal's stored price must block, even though the link itself is fine."""
    from src.db.models import Merchant, MerchantProduct
    from src.db.session import session_scope
    from src.services.generation import revalidate

    now = datetime.now(timezone.utc)
    with session_scope() as s:
        _make_deal(s, "deal-price", "amazon", "https://www.amazon.in/dp/PRICE1", current_price=1000.0)
        merchant = s.scalar(select(Merchant).where(Merchant.key == "amazon"))
        s.add(MerchantProduct(
            merchant_id=merchant.id, external_id="PRICE1",
            product_url="https://www.amazon.in/dp/PRICE1",
            current_price=1300.0, availability="in_stock", last_verified_at=now,
        ))

    verdict = revalidate.revalidate_deals(["deal-price"], max_staleness_min=30)
    assert verdict["ok"] is False
    assert "price risen" in verdict["reason"]


def test_fresh_in_stock_product_within_tolerance_passes():
    """A fresh product with a price within the 10% tolerance is OK."""
    from src.db.models import Merchant, MerchantProduct
    from src.db.session import session_scope
    from src.services.generation import revalidate

    now = datetime.now(timezone.utc)
    with session_scope() as s:
        _make_deal(s, "deal-ok", "amazon", "https://www.amazon.in/dp/OK1", current_price=1000.0)
        merchant = s.scalar(select(Merchant).where(Merchant.key == "amazon"))
        s.add(MerchantProduct(
            merchant_id=merchant.id, external_id="OK1",
            product_url="https://www.amazon.in/dp/OK1",
            current_price=1050.0, availability="in_stock", last_verified_at=now,
        ))

    verdict = revalidate.revalidate_deals(["deal-ok"], max_staleness_min=30)
    assert verdict["ok"] is True


def test_publisher_blocks_and_never_sends_on_failed_revalidation(monkeypatch):
    """The wiring in Publisher.publish(): a failing verdict must land the post
    in BLOCKED with a 'blocked_stale:' note and never reach the actual send."""
    from src.db.models_generation import GeneratedPost, PostStatus
    from src.db.session import session_scope
    from src.services.generation.publishing import Publisher
    from src.config.settings import get_settings

    with session_scope() as s:
        _make_deal(s, "deal-pub", "ajio", "https://www.ajio.com/p/pub")
        post = GeneratedPost(generated_at=datetime.now(timezone.utc), post_type="single",
                             deal_ids=["deal-pub"], rendered_text="text", status=PostStatus.DRAFT)
        s.add(post)
        s.flush()
        post_id = post.id

    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_api_id", 123)
    monkeypatch.setattr(settings, "telegram_api_hash", "hash")
    monkeypatch.setattr(
        "src.services.generation.revalidate.revalidate_deals",
        lambda deal_ids, max_staleness_min: {"ok": False, "reason": "dead link (404)"},
    )

    result = Publisher().publish(post_id, "@testchannel", confirm=True)
    assert result["ok"] is False
    assert result["status"] == PostStatus.BLOCKED
    assert result["note"].startswith("blocked_stale:")

    with session_scope() as s:
        refreshed = s.get(GeneratedPost, post_id)
        assert refreshed.status == PostStatus.BLOCKED
