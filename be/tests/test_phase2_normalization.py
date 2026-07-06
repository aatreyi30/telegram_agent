"""Phase 2 parser tests — deterministic, no DB/network.

Locks in the extraction behaviour that must never silently regress, especially
the no-guessing rules (currency-anchored prices, cue-anchored coupons, merchant
only from known link domains).
"""

from __future__ import annotations

from src.services.processing import parser


def test_prices_require_currency_anchor():
    prices = parser.parse_prices("MRP ₹1999 Now Rs.699 or INR 499. Call 9876543210")
    amounts = sorted(p.amount for p in prices)
    assert amounts == [499.0, 699.0, 1999.0]
    # the 10-digit phone number is NOT parsed as a price
    assert all(p.amount < 100000 for p in prices)


def test_prices_handle_thousands_separator():
    prices = parser.parse_prices("AJIO Rate: ₹15,304/gm ₹1,500 OFF")
    amounts = sorted(p.amount for p in prices)
    assert amounts == [1500.0, 15304.0]


def test_price_threshold():
    assert parser.parse_price_threshold("Men's Fashion Under ₹200 🔥") == 200.0
    assert parser.parse_price_threshold("no ceiling here") is None


def test_coupons_are_cue_anchored():
    coupons = dict(parser.parse_coupons("Use Coupon SAVE100 and code: DHANVARSHA2"))
    assert "SAVE100" in coupons
    assert "DHANVARSHA2" in coupons
    # a bare uppercase word without a cue is NOT a coupon
    assert parser.parse_coupons("BOAT AIRDOPES DEAL") == []


def test_emoji_and_hashtag_extraction():
    assert parser.parse_emojis("Gold Deal 🔥💰⚡") == ["🔥", "💰", "⚡"]
    assert parser.parse_hashtags("Loot #amazon #kitchen #amazon") == ["amazon", "kitchen"]


def test_classify_link_shortener_and_merchant_free():
    info = parser.classify_link("https://grbn.in/PukQzK")
    assert info.domain == "grbn.in"
    assert info.is_shortlink is True

    info2 = parser.classify_link("https://www.amazon.in/dp/B0ABC?tag=aff-21&utm_source=tg")
    assert info2.domain == "www.amazon.in"
    assert info2.is_shortlink is False
    assert info2.tracking_params and info2.tracking_params.get("tag") == "aff-21"


def test_merchant_detection_only_from_known_domains():
    from src.services.collection.merchants.registry import detect_merchant_key

    # shortlink -> unknown (never guessed, even if text mentions a brand)
    assert detect_merchant_key("https://grbn.in/PukQzK") is None
    assert detect_merchant_key("https://www.amazon.in/dp/B0ABC") == "amazon"
    assert detect_merchant_key("https://dl.flipkart.com/dl/x") == "flipkart"
