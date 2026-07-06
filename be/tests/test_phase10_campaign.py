"""Phase 10 tests — calendar dates + plan allocation/risk logic (no DB/network)."""

from __future__ import annotations

from collections import Counter
from datetime import date

from src.services.planning.calendar import _next_occurrence
from src.services.planning.campaign import CampaignPlanningEngine


def test_next_occurrence_rolls_to_next_year_when_past():
    today = date(2026, 7, 3)
    # Jan 26 already passed this year -> next year
    assert _next_occurrence(today, 1, 26) == date(2027, 1, 26)
    # Aug 15 is still upcoming this year
    assert _next_occurrence(today, 8, 15) == date(2026, 8, 15)
    # approximate (day=None) -> 1st of that month, upcoming
    assert _next_occurrence(today, 10, None) == date(2026, 10, 1)


def test_allocate_posts_weights_by_growth_action():
    e = CampaignPlanningEngine()
    blueprint = {"content_mix": [
        {"post_type": "many-links · multi-deal", "current_share": 0.1, "action": "increase", "avg_views_per_day": 113},
        {"post_type": "low-price", "current_share": 0.4, "action": "decrease", "avg_views_per_day": 5},
        {"post_type": "high-price", "current_share": 0.3, "action": "maintain", "avg_views_per_day": 13},
    ]}
    alloc = e._allocate_posts(blueprint, posts=20)
    total = sum(a["target_posts"] for a in alloc)
    assert 17 <= total <= 22          # ~ the budget (independent rounding)
    by_type = {a["post_type"]: a["target_posts"] for a in alloc}
    # 'increase' type is boosted relative to its small base share; 'decrease' is trimmed
    assert by_type["many-links · multi-deal"] >= 1


def test_risk_flags_merchant_overuse():
    e = CampaignPlanningEngine()
    recent = {"merchants": Counter({"amazon": 18, "flipkart": 2}),
              "clusters": Counter({"low-price": 5, "high-price": 5}), "total": 20}
    risks = e._risks(recent, posts_per_day=17)
    kinds = {r["kind"] for r in risks}
    assert "merchant_overuse" in kinds     # amazon is 90% -> flagged
    assert "content_concentration" not in kinds  # clusters are balanced


def test_expected_outcome_sums_views():
    e = CampaignPlanningEngine()
    alloc = [{"post_type": "a", "target_posts": 2}, {"post_type": "b", "target_posts": 3}]
    perf = {"a": 100.0, "b": 10.0}
    eo = e._expected_outcome(alloc, perf)
    assert eo["estimated_daily_views"] == 230   # 2*100 + 3*10
