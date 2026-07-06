"""Phase 4 tests — metric aggregation + honesty guards (no DB/network)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.services.intelligence.merchant import MerchantIntelligenceEngine, _minmax
from src.services.metrics.merchant_metrics import MerchantMetrics, OwnedPostFact

NOW = datetime(2026, 7, 3, tzinfo=timezone.utc)


def test_minmax_needs_two_distinct_values():
    assert _minmax({"a": 5.0}) == {}                 # single merchant -> not comparable
    assert _minmax({"a": 3.0, "b": 3.0}) == {}       # all equal -> not comparable
    out = _minmax({"a": 0.0, "b": 10.0, "c": 5.0})
    assert out == {"a": 0.0, "b": 1.0, "c": 0.5}


def test_summary_age_normalizes_views():
    # two posts, same cumulative views but different ages -> different views/day
    m = MerchantMetrics(merchant_key="amazon")
    m.posts.append(OwnedPostFact(1, NOW - timedelta(days=10), views=100, forwards=2, reactions=None))
    m.posts.append(OwnedPostFact(2, NOW - timedelta(days=1), views=100, forwards=4, reactions=None))
    s = m.summary(NOW)
    assert s["post_count"] == 2
    assert s["avg_views"] == 100.0
    # views/day: 100/10=10 and 100/1=100 -> mean 55
    assert abs(s["avg_views_per_day"] - 55.0) < 1e-6
    assert s["avg_forwards"] == 3.0
    assert s["avg_reactions"] is None  # never fabricated when all None


def test_window_summary_filters_by_recency():
    m = MerchantMetrics(merchant_key="amazon")
    m.posts.append(OwnedPostFact(1, NOW - timedelta(days=2), 50, 1, None))
    m.posts.append(OwnedPostFact(2, NOW - timedelta(days=40), 50, 1, None))
    w7 = m.window_summary(NOW, 7)
    w30 = m.window_summary(NOW, 30)
    all_w = m.window_summary(NOW, 0)
    assert w7["post_count"] == 1
    assert w30["post_count"] == 1
    assert all_w["post_count"] == 2


def test_underutilized_opportunity_suppressed_when_coverage_low():
    engine = MerchantIntelligenceEngine()
    # a merchant we appear not to post, but a competitor does
    summaries = {
        "flipkart": {
            "post_count": 0, "competitor_post_count": 5, "competitor_count": 1,
        }
    }
    metrics = {"flipkart": MerchantMetrics(merchant_key="flipkart")}

    low = engine._detect_opportunities(metrics, summaries, NOW, resolution_coverage=0.2)
    assert low == []  # absence is not evidence when we can't see our own merchants

    high = engine._detect_opportunities(metrics, summaries, NOW, resolution_coverage=0.9)
    kinds = [o["kind"] for o in high]
    assert "underutilized_vs_competitors" in kinds
