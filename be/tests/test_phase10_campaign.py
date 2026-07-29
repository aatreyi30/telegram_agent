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


def test_weekly_plan_ramps_cadence_for_an_event_landing_this_week():
    """A seeded sale event (Independence Day Sale, Big Billion Days, ...) whose date
    falls within the plan's week must automatically bump posts_per_day/week by the same
    _RAMP multiplier _event_plan() uses, bias merchant_priorities toward its merchant,
    and record the ramp so the digest/UI can say WHY the numbers jumped."""
    e = CampaignPlanningEngine()
    today = date(2026, 8, 10)  # Monday
    blueprint = {"posting_frequency_baseline": 10}
    events_in_week = [{"name": "Flipkart Big Billion Days", "event_type": "merchant_sale",
                       "merchant_key": "flipkart", "next_date": date(2026, 8, 13),
                       "days_away": 3, "date_confidence": "approximate"}]
    plan = e._weekly_plan(blueprint, perf=[], today=today, events=events_in_week)
    bp = plan["blueprint"]
    assert bp["event_ramp"] is not None
    assert bp["event_ramp"]["baseline_posts_per_day"] == 10
    assert bp["event_ramp"]["ramped_posts_per_day"] == 30       # merchant_sale -> 3.0x
    assert bp["posts_per_day"] == 30
    assert bp["posts_per_week"] == 210
    assert all(d["posts_planned"] == 30 for d in bp["daily_themes"])


def test_weekly_plan_no_ramp_when_event_is_outside_the_week():
    e = CampaignPlanningEngine()
    today = date(2026, 8, 10)
    blueprint = {"posting_frequency_baseline": 10}
    events_far = [{"name": "Independence Day Sale", "event_type": "festival",
                  "merchant_key": None, "next_date": date(2026, 9, 1),
                  "days_away": 22, "date_confidence": "exact"}]
    plan = e._weekly_plan(blueprint, perf=[], today=today, events=events_far)
    bp = plan["blueprint"]
    assert bp["event_ramp"] is None
    assert bp["posts_per_day"] == 10   # unramped baseline


def test_weekly_plan_context_only_event_does_not_ramp_even_when_nearest():
    """A plain observance/holiday (e.g. "International Cat Day", a gazetted holiday)
    landing this week must NOT ramp cadence — only merchant_sale/festival/shopping
    (the _RAMP-keyed types) do. It should still be visible in upcoming_events so the
    AI can mention it in the narrative, just without a fabricated 1.5x fallback ramp."""
    e = CampaignPlanningEngine()
    today = date(2026, 8, 10)  # Monday
    blueprint = {"posting_frequency_baseline": 10}
    events_in_week = [
        {"name": "International Cat Day", "event_type": "observance",
         "merchant_key": None, "next_date": date(2026, 8, 12),
         "days_away": 2, "date_confidence": "exact"},
        {"name": "Independence Day", "event_type": "gazetted_holiday",
         "merchant_key": None, "next_date": date(2026, 8, 15),
         "days_away": 5, "date_confidence": "exact"},
    ]
    plan = e._weekly_plan(blueprint, perf=[], today=today, events=events_in_week)
    bp = plan["blueprint"]
    assert bp["event_ramp"] is None
    assert bp["posts_per_day"] == 10   # unramped baseline
    assert [ev["name"] for ev in bp["upcoming_events"]] == ["International Cat Day", "Independence Day"]


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
    # each row carries WHY its share was chosen — the Plan page's deal-type reasoning
    # reads this instead of a views tautology.
    by_action = {a["post_type"]: a["action"] for a in alloc}
    assert by_action["low-price"] == "decrease" and by_action["high-price"] == "maintain"
    # 'increase' type is boosted relative to its small base share; 'decrease' is trimmed
    assert by_type["many-links · multi-deal"] >= 1


def test_cold_start_allocation_uses_competitor_reference():
    # No owned content_mix and no owned history: the split must come from the Growth
    # cold-start blueprint's competitor-derived reference, not a hardcoded default.
    e = CampaignPlanningEngine()
    blueprint = {"content_mix_reference": {"loot_deal": 80, "single_deal": 20}}
    alloc = e._allocate_posts(blueprint, posts=10, recent={"post_types": {}})
    by_type = {a["post_type"]: a["target_posts"] for a in alloc}
    assert by_type.get("loot_deal", 0) > by_type.get("single_deal", 0)   # 80/20 skew honored
    assert sum(by_type.values()) == 10


def test_cold_start_allocation_neutral_default_when_nothing_known():
    # No owned history AND no competitor reference -> neutral 60/40 single/loot,
    # never an empty allocation.
    e = CampaignPlanningEngine()
    alloc = e._allocate_posts({}, posts=10, recent={"post_types": {}})
    by_type = {a["post_type"]: a["target_posts"] for a in alloc}
    assert sum(by_type.values()) == 10
    assert by_type.get("single_deal", 0) >= by_type.get("loot_deal", 0)


def test_deal_type_reasoning_explains_the_pattern_not_percentages():
    """The 'Why' column must state the WINDOW the split was learned from (all-time
    history / last 45 days / competitor reference / neutral default) and the PATTERN
    found there (outperforms / underperforms / about even) in plain language — no raw
    share percentages, and no views-tie tautology restating the count."""
    from src.controllers.service import _reason_deal_type_split

    alloc = [
        {"post_type": "single_deal", "target_posts": 18, "current_share": 0.514,
         "action": "maintain", "source_kind": "all_time"},
        {"post_type": "loot_deal", "target_posts": 17, "current_share": 0.486,
         "action": "maintain", "source_kind": "all_time"},
    ]
    _reason_deal_type_split(alloc, history_days=240)   # 240 days -> months, not a vague "all-time"
    for a in alloc:
        assert "%" not in a["reasoning"]
        assert "months of posting" in a["reasoning"]
        assert "about the same" in a["reasoning"]
    # tied counts differ by 1 (18 vs 17) — that's just rounding, not a contradiction of
    # "about the same"; the Why must say so, or it reads as a single/loot mismatch.
    assert "rounding" in alloc[0]["reasoning"]
    assert "rounding" in alloc[1]["reasoning"]

    # a short history (< 60 days) states days, not months
    short = [{"post_type": "single_deal", "target_posts": 5, "current_share": 0.5,
              "action": "maintain", "source_kind": "all_time"},
             {"post_type": "loot_deal", "target_posts": 5, "current_share": 0.5,
              "action": "maintain", "source_kind": "all_time"}]
    _reason_deal_type_split(short, history_days=20)
    assert "20 days of posting" in short[0]["reasoning"]
    assert "evenly" in short[0]["reasoning"] and "rounding" not in short[0]["reasoning"]

    inc = [{"post_type": "loot_deal", "target_posts": 12, "current_share": 0.2,
            "action": "increase", "source_kind": "all_time"},
           {"post_type": "single_deal", "target_posts": 8, "current_share": 0.8,
            "action": "decrease", "source_kind": "all_time"}]
    _reason_deal_type_split(inc)
    assert "%" not in inc[0]["reasoning"] and "more views per post" in inc[0]["reasoning"]
    assert "%" not in inc[1]["reasoning"] and "fewer views per post" in inc[1]["reasoning"]

    # Regression: 'maintain' with a SKEWED recent share (64/36) but a near-even final
    # split (18/17, because the AI plan / 30% variety floor pulled it there, not a
    # rounding artifact of the share) must NOT claim "just rounding" — that blames
    # rounding for a gap that's actually the AI/floor's doing, a false mechanism.
    skewed = [{"post_type": "single_deal", "target_posts": 18, "current_share": 0.644,
               "action": "maintain", "source_kind": "recent_30d"},
              {"post_type": "loot_deal", "target_posts": 17, "current_share": 0.356,
               "action": "maintain", "source_kind": "recent_30d"}]
    _reason_deal_type_split(skewed)
    for a in skewed:
        assert "rounding" not in a["reasoning"]
        assert "about the same" in a["reasoning"]
        assert "18 of 35" in a["reasoning"] or "17 of 35" in a["reasoning"]

    # The common case: the split was learned from the SAME 30-day window as the displayed
    # avg-views figure — must say "last 30 days", never the longer all-time span, even
    # when a real history_days is passed in (it must be ignored for this source_kind).
    d30 = [{"post_type": "single_deal", "target_posts": 6, "current_share": 0.6,
            "action": "maintain", "source_kind": "recent_30d"}]
    _reason_deal_type_split(d30, history_days=400)
    assert "last 30 days" in d30[0]["reasoning"] and "month" not in d30[0]["reasoning"]

    rec = [{"post_type": "single_deal", "target_posts": 6, "current_share": 0.6,
            "action": None, "source_kind": "recent"}]
    _reason_deal_type_split(rec)
    assert "%" not in rec[0]["reasoning"] and "last 45 days" in rec[0]["reasoning"]


def test_risk_flags_merchant_overuse():
    e = CampaignPlanningEngine()
    recent = {"merchants": Counter({"amazon": 18, "flipkart": 2}),
              "post_types": Counter({"single_deal": 5, "loot_deal": 5}), "total": 20}
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
