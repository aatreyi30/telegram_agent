"""Phase 7 tests — growth-engine helper logic (deterministic, no DB/network)."""

from __future__ import annotations

from types import SimpleNamespace

from src.services.intelligence.growth import GrowthEngine, plain_label


def test_plain_label_translates_cluster_signatures():
    assert "loot" in plain_label("many-links · multi-deal · price-capped").lower()
    assert "coupon" in plain_label("coupon-heavy · emoji-rich").lower()
    assert "budget" in plain_label("low-price").lower()
    assert plain_label(None) == "posts"


def _perf(post_type, share, vpd):
    return SimpleNamespace(post_type=post_type, share=share, avg_views_per_day=vpd)


def test_channel_type_derived_from_descriptor():
    e = GrowthEngine()
    assert e._channel_type_from_descriptor("coupon-heavy · emoji-rich") == "coupon-led"
    assert e._channel_type_from_descriptor("many-links · multi-deal") == "loot-led"
    assert e._channel_type_from_descriptor("single-item · low-price") == "single-deal-led"
    assert e._channel_type_from_descriptor("high-price") == "hybrid"


def test_channel_type_from_mix_uses_dominant():
    e = GrowthEngine()
    assert e._channel_type_from_mix({"coupon-heavy": 50, "high-price": 10}) == "coupon-led"
    assert e._channel_type_from_mix({}) == "unknown"


def test_lift_is_pct_vs_baseline():
    e = GrowthEngine()
    assert e._lift(150.0, 100.0) == 50.0
    assert e._lift(50.0, 100.0) == -50.0
    assert e._lift(None, 100.0) == 0.0


def test_content_mix_actions():
    e = GrowthEngine()
    perf = [_perf("hot", 0.1, 200.0), _perf("mid", 0.4, 100.0), _perf("cold", 0.5, 20.0)]
    mix = {m["post_type"]: m["action"] for m in e._content_mix(perf)}
    # median vpd = 100; >=125 -> increase, <=75 -> decrease
    assert mix["hot"] == "increase"
    assert mix["mid"] == "maintain"
    assert mix["cold"] == "decrease"


def test_posting_plan_spreads_across_day_and_conserves_volume():
    e = GrowthEngine()
    # 24 hourly rows: afternoon performs best, morning worst
    hourly = []
    for h in range(24):
        if 12 <= h <= 17:
            hourly.append([h, 30.0, 100])   # strong, high volume
        elif 6 <= h <= 11:
            hourly.append([h, 5.0, 100])     # weak
        else:
            hourly.append([h, 15.0, 50])     # middling
    plan = e._build_posting_plan(posts_per_day=20, hourly_all=hourly)
    assert plan is not None
    parts = {p["part"]: p for p in plan}
    # every active day-part is present (spread), none collapsed to zero
    assert len(plan) == 4
    assert all(p["recommended_posts_per_day"] >= 1 for p in plan)
    # afternoon (strongest) gets the most; morning (weakest) is reduced
    assert parts["Afternoon"]["recommended_posts_per_day"] >= parts["Morning"]["recommended_posts_per_day"]
    assert parts["Morning"]["action"] == "reduce"
    # total stays in the neighbourhood of the daily budget (not all at one time)
    total = sum(p["recommended_posts_per_day"] for p in plan)
    assert 15 <= total <= 25


def test_posting_plan_needs_data():
    e = GrowthEngine()
    assert e._build_posting_plan(posts_per_day=None, hourly_all=[[1, 2.0, 3]]) is None
    assert e._build_posting_plan(posts_per_day=10, hourly_all=None) is None


def test_positive_emojis_only_keeps_above_baseline():
    e = GrowthEngine()
    recs = [
        SimpleNamespace(metric_value=150, comparison_value=100, evidence={"emoji": "👉"}),
        SimpleNamespace(metric_value=60, comparison_value=100, evidence={"emoji": "💰"}),
    ]
    assert e._positive_emojis(recs) == ["👉"]  # the below-baseline emoji is dropped
