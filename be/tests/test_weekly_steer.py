"""enforce_weekly_constraints: the weekly plan has no per-post slots, so a steer can only
move direction-level knobs — merchant_priorities, the loot/single lean, and posts/day.
Must mutate the blueprint honestly and say plainly what a weekly steer can't reach
(price/time/category are per-slot, daily-only)."""
from __future__ import annotations

from src.services.generation.directives import enforce_weekly_constraints


def _bp():
    return {
        "posts_per_day": 10, "posts_per_week": 70,
        "loot_deal_ratio": {"loot": 40, "deal": 60},
        "merchant_priorities": [{"merchant": "amazon"}, {"merchant": "flipkart"},
                                {"merchant": "ajio"}],
        "daily_themes": [{"day": "Mon", "posts_planned": 10, "loot_share": 0.4, "single_share": 0.6}],
    }


def _intent(**over):
    base = {"merchants": None, "categories": None, "exclude_merchants": None,
            "exclude_categories": None, "after_min": None, "before_min": None,
            "price_min": None, "price_max": None, "target_posts": None, "pause": False,
            "type_lean": None}
    base.update(over)
    return base


def test_merchants_only_narrows_priorities():
    bp = _bp()
    notes = enforce_weekly_constraints(bp, _intent(merchants={"amazon"}))
    assert bp["merchant_priorities"] == [{"merchant": "amazon"}]
    assert any("narrowed to amazon" in n for n in notes)


def test_merchants_only_with_no_match_leaves_priorities_unchanged():
    bp = _bp()
    original = list(bp["merchant_priorities"])
    notes = enforce_weekly_constraints(bp, _intent(merchants={"myntra"}))
    assert bp["merchant_priorities"] == original
    assert any("none of your requested merchants" in n for n in notes)


def test_exclude_merchants_drops_from_priorities():
    bp = _bp()
    notes = enforce_weekly_constraints(bp, _intent(exclude_merchants={"ajio"}))
    assert {p["merchant"] for p in bp["merchant_priorities"]} == {"amazon", "flipkart"}
    assert any("dropped from this week's merchant priorities" in n for n in notes)


def test_type_lean_nudges_ratio_within_the_30_70_band():
    bp = _bp()
    enforce_weekly_constraints(bp, _intent(type_lean="loot"))
    assert bp["loot_deal_ratio"] == {"loot": 65, "deal": 35}
    assert bp["daily_themes"][0]["loot_share"] == 0.65

    bp2 = _bp()
    enforce_weekly_constraints(bp2, _intent(type_lean="single"))
    assert bp2["loot_deal_ratio"] == {"loot": 35, "deal": 65}


def test_target_posts_sets_posts_per_day_not_per_week():
    """Weekly's post-count analogue is posts/day (the daily plan's recommended_posts
    figure) — a bare 'post 20' at the weekly level must NOT be read as 20 for the whole
    week (that would silently starve every day down to ~3 posts)."""
    bp = _bp()
    notes = enforce_weekly_constraints(bp, _intent(target_posts=20))
    assert bp["posts_per_day"] == 20
    assert bp["posts_per_week"] == 140
    assert any("posts/day set to 20" in n for n in notes)


def test_target_posts_period_week_divides_down_to_per_day():
    """Regression: 'let us target 40 posts this week' was silently read as 40/DAY
    (280/week — a 7x overshoot) instead of the operator's actual weekly total. When
    target_posts_period == 'week', the per-day figure must be derived (40/7 ~ 6), and
    posts_per_week must hold the operator's real total (40), not a multiplied-up guess."""
    bp = _bp()
    notes = enforce_weekly_constraints(bp, _intent(target_posts=40, target_posts_period="week"))
    assert bp["posts_per_day"] == 6          # round(40/7)
    assert bp["posts_per_week"] == 40        # the operator's actual total, unmultiplied
    assert bp["daily_themes"][0]["posts_planned"] == 6
    assert any("posts/week set to 40" in n and "~6/day" in n for n in notes)


def test_target_posts_period_day_still_defaults_per_day():
    bp = _bp()
    enforce_weekly_constraints(bp, _intent(target_posts=15, target_posts_period="day"))
    assert bp["posts_per_day"] == 15
    assert bp["posts_per_week"] == 105
    assert bp["daily_themes"][0]["posts_planned"] == 15


def test_price_time_category_are_honestly_unsupported_at_weekly_scope():
    bp = _bp()
    notes = enforce_weekly_constraints(bp, _intent(price_max=1000, after_min=600, categories={"general"}))
    joined = " ".join(notes)
    assert "price" in joined and "daily plan" in joined
    assert "timing" in joined
    assert "category" in joined


def test_no_steer_fields_set_is_a_no_op():
    bp = _bp()
    original = {k: v for k, v in bp.items()}
    notes = enforce_weekly_constraints(bp, _intent())
    assert notes == []
    assert bp == original