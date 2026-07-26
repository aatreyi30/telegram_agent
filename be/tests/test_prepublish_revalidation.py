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
    # Publisher now asks for PER-DEAL verdicts so a multi-deal board can drop a dead
    # item instead of dying whole. This post carries one deal — there is nothing to
    # salvage, so it must still block exactly as before.
    monkeypatch.setattr(
        "src.services.generation.revalidate.revalidate_each",
        lambda deal_ids, max_staleness_min: {d: {"ok": False, "reason": "dead link (404)"}
                                             for d in deal_ids},
    )

    result = Publisher().publish(post_id, "@testchannel", confirm=True)
    assert result["ok"] is False
    assert result["status"] == PostStatus.BLOCKED
    assert result["note"].startswith("blocked_stale:")

    with session_scope() as s:
        refreshed = s.get(GeneratedPost, post_id)
        assert refreshed.status == PostStatus.BLOCKED


def _make_board(s, n, prefix):
    """A loot board of `n` deals rendered as one message, one line per deal."""
    from src.db.models_generation import GeneratedPost, PostStatus

    items = []
    for i in range(n):
        did, url = f"{prefix}-{i}", f"https://www.ajio.com/p/{prefix}{i}"
        _make_deal(s, did, "ajio", url)
        items.append({"deal_id": did, "line": f"Pick {i} - {url}"})
    text = "Fashion Under 999\n\n" + "\n".join(i["line"] for i in items) + "\n\nShare it!"
    post = GeneratedPost(generated_at=datetime.now(timezone.utc), post_type="collection",
                         deal_ids=[i["deal_id"] for i in items], rendered_text=text,
                         format_meta={"items": items}, status=PostStatus.DRAFT)
    s.add(post)
    s.flush()
    return post.id


def _publish_board(monkeypatch, post_id, dead_ids, sent):
    from src.config.settings import get_settings
    from src.services.generation.publishing import Publisher

    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_api_id", 123)
    monkeypatch.setattr(settings, "telegram_api_hash", "hash")
    monkeypatch.setattr(
        "src.services.generation.revalidate.revalidate_each",
        lambda deal_ids, max_staleness_min: {
            d: {"ok": d not in dead_ids, "reason": "dead link (404)"} for d in deal_ids},
    )

    async def fake_send(self, pid, channel_ref, confirm):
        from src.db.session import session_scope as scope
        with scope() as s:
            from src.db.models_generation import GeneratedPost
            sent.append(s.get(GeneratedPost, pid).rendered_text)
        return True, "Sent (fake)."

    monkeypatch.setattr(Publisher, "_check_and_publish", fake_send)
    return Publisher().publish(post_id, "@testchannel", confirm=True)


def test_one_dead_deal_does_not_kill_the_whole_board(monkeypatch):
    """THE bug: a 10-deal board died because item #7 sold out, throwing away nine
    live deals. It must now send the survivors, minus the dead line."""
    from src.db.models_generation import GeneratedPost, PostStatus
    from src.db.session import session_scope

    with session_scope() as s:
        post_id = _make_board(s, 6, "boardA")

    sent: list[str] = []
    result = _publish_board(monkeypatch, post_id, {"boardA-2"}, sent)

    assert result["ok"] is True
    assert result["status"] == PostStatus.PUBLISHED
    assert len(sent) == 1
    assert "boardA2" not in sent[0], "the dead deal's link still went out"
    for keep in (0, 1, 3, 4, 5):
        assert f"boardA{keep}" in sent[0]
    assert "Fashion Under 999" in sent[0] and "Share it!" in sent[0]
    assert "Dropped 1 of 6 deals" in result["note"]

    with session_scope() as s:
        refreshed = s.get(GeneratedPost, post_id)
        assert refreshed.deal_ids == ["boardA-0", "boardA-1", "boardA-3", "boardA-4", "boardA-5"], \
            "what we recorded must match what the channel received"


def test_board_stripped_below_the_floor_is_blocked(monkeypatch):
    """Trimming is not unconditional — a board down to two links is not worth posting."""
    from src.db.models_generation import PostStatus
    from src.db.session import session_scope

    with session_scope() as s:
        post_id = _make_board(s, 5, "boardB")

    sent: list[str] = []
    result = _publish_board(monkeypatch, post_id, {"boardB-0", "boardB-1", "boardB-2"}, sent)

    assert result["ok"] is False
    assert result["status"] == PostStatus.BLOCKED
    assert "only 2 of 5 deals survived" in result["note"]
    assert sent == [], "nothing may reach the channel when the board is blocked"
