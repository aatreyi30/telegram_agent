"""Phase 5 tests — behaviour aggregation + honesty guards (no DB/network)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.services.intelligence.competitor import (
    CompetitorIntelligenceEngine,
    _cosine,
    _style_vector,
)
from src.services.metrics.competitor_metrics import ChannelBehaviour, PostFeature

UTC = timezone.utc


def _pf(**kw) -> PostFeature:
    base = dict(
        posted_at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC), text_len=100, has_media=False,
        views=None, num_links=1, has_coupon=False, is_multi_deal=False, emoji_count=0,
        hashtag_count=0, has_cta=False, merchant_key=None, cluster=None,
        known_link_count=0, total_link_count=1,
    )
    base.update(kw)
    return PostFeature(**base)


def test_behaviour_rates_and_ist_hour():
    ch = ChannelBehaviour(label="c")
    # UTC 09:00 -> IST 14:30 -> hour 14
    ch.features = [
        _pf(has_cta=True, has_coupon=True, cluster="coupon-heavy"),
        _pf(has_cta=False, has_coupon=False, cluster="coupon-heavy"),
    ]
    s = ch.summary()
    assert s["post_count"] == 2
    assert s["cta_rate"] == 0.5
    assert s["coupon_rate"] == 0.5
    assert s["top_posting_hour_ist"] == 14
    assert s["deal_mix"] == {"coupon-heavy": 2}


def test_merchant_coverage_is_fraction_of_resolved_links():
    ch = ChannelBehaviour(label="c")
    ch.features = [
        _pf(total_link_count=2, known_link_count=1),
        _pf(total_link_count=2, known_link_count=0),
    ]
    # 1 known of 4 total = 0.25
    assert ch.summary()["merchant_coverage"] == 0.25


def test_cosine_and_style_vector():
    a = {"cta_rate": 1.0, "coupon_rate": 0.0}
    assert _cosine(_style_vector(a), _style_vector(a)) == 1.0
    assert _cosine([0, 0], [1, 1]) is None  # zero vector -> undefined, not fabricated


def test_cadence_compared_over_same_window():
    engine = CompetitorIntelligenceEngine()
    # 30 owned posts spread across Jul 1..Jul 30
    owned_dates = [datetime(2026, 7, d, 12, 0, tzinfo=UTC) for d in range(1, 31)]
    # competitor's snapshot window is a single day
    start = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
    end = datetime(2026, 7, 15, 20, 0, tzinfo=UTC)
    ppd = engine._owned_cadence_in_window(owned_dates, start, end)
    # exactly 1 owned post (Jul 15 12:00) falls in the window, span 1 day
    assert ppd == 1.0


def test_baseline_cluster_excluded_from_opportunities():
    engine = CompetitorIntelligenceEngine()
    owned = {"posts_per_day": 5.0, "deal_mix": {"coupon-heavy": 10}}
    owned_dates = [datetime(2026, 7, 1, tzinfo=UTC)]
    comp = {
        1: {
            "post_count": 40, "label": "x", "posts_per_day": 3.0,
            "first_posted_at": datetime(2026, 7, 1, tzinfo=UTC),
            "last_posted_at": datetime(2026, 7, 2, tzinfo=UTC),
            "deal_mix": {"baseline (near dataset average)": 38, "coupon-heavy": 2},
        }
    }
    signals = engine._detect_signals(owned, owned_dates, comp)
    kinds = [(s["signal_type"], s["kind"], s["evidence"].get("cluster")) for s in signals]
    # baseline must NOT appear as an underused_deal_type opportunity
    assert not any(k[1] == "underused_deal_type" and "baseline" in str(k[2]) for k in kinds)
