"""Steer-directive -> hard constraint enforcement (no DB / no AI):
- free text is parsed into merchant/category allow-lists ONLY on a restriction cue,
  matched against real feed slugs; and into a clock window;
- enforcement pins slots to allowed merchants/categories keeping every pair feed-valid;
- a hard time window places every slot inside it, unique + chronological + off-grid.
These are the deterministic guarantees the UI relies on when an operator steers a plan."""
from __future__ import annotations

from src.services.generation.directives import (parse_directive_constraints,
                                                 enforce_pair_constraints)
from src.services.generation.ai_execution import _place_in_window, _slot_minute

MERCH = ["ajio", "amazon", "flipkart", "myntra"]
CATS = ["beauty-and-personal-care", "electronics-and-gadgets", "fashion-and-lifestyle", "general"]
FEED = {("amazon", "electronics-and-gadgets"): 5, ("flipkart", "electronics-and-gadgets"): 6,
        ("flipkart", "fashion-and-lifestyle"): 3, ("ajio", "fashion-and-lifestyle"): 5,
        ("myntra", "general"): 1, ("amazon", "beauty-and-personal-care"): 4}


def test_lean_without_cue_does_not_pin():
    # "post more loot" / "push electronics" are soft leans the AI handles — not hard pins.
    c = parse_directive_constraints("Post more loot boards today", MERCH, CATS)
    assert c["merchants"] is None and c["categories"] is None
    assert parse_directive_constraints("push electronics hard, less fashion", MERCH, CATS)["categories"] is None


def test_only_pins_merchants_matched_to_feed():
    c = parse_directive_constraints("Focus on Amazon and Flipkart only", MERCH, CATS)
    assert c["merchants"] == {"amazon", "flipkart"}
    # a merchant not in the feed is never invented into the allow-list
    assert parse_directive_constraints("only nike deals", MERCH, CATS)["merchants"] is None


def test_time_window_word_plus_clock():
    a, b = (parse_directive_constraints("post only in the evening, 6pm onwards")["after_min"],
            parse_directive_constraints("post only in the evening, 6pm onwards")["before_min"])
    assert a == 18 * 60 and b == 24 * 60
    c = parse_directive_constraints("only in the morning, before 9am")
    assert c["after_min"] == 6 * 60 and c["before_min"] == 9 * 60


def test_enforce_merchant_pins_and_keeps_pairs_valid():
    slots = [{"merchant": "ajio", "theme": "fashion-and-lifestyle", "why": "x"},
             {"merchant": "myntra", "theme": "general", "why": "x"},
             {"merchant": "amazon", "theme": "electronics-and-gadgets", "why": "x"}]
    enforce_pair_constraints(slots, {"merchants": {"amazon", "flipkart"}}, FEED)
    assert all(s["merchant"] in {"amazon", "flipkart"} for s in slots)
    # every resulting (merchant, category) is a real feed pair jit_fill can fill
    assert all((s["merchant"], s["theme"]) in FEED for s in slots)


def test_enforce_category_pins_theme():
    slots = [{"merchant": "ajio", "theme": "fashion-and-lifestyle", "why": "x"},
             {"merchant": "amazon", "theme": "beauty-and-personal-care", "why": "x"}]
    enforce_pair_constraints(slots, {"categories": {"electronics-and-gadgets"}}, FEED)
    assert all(s["theme"] == "electronics-and-gadgets" for s in slots)
    assert all((s["merchant"], s["theme"]) in FEED for s in slots)


def test_enforce_merchant_and_category_jointly():
    """The case the old two-pass version broke: BOTH constraints must hold at once."""
    slots = [{"merchant": "ajio", "theme": "fashion-and-lifestyle", "why": "x"},
             {"merchant": "myntra", "theme": "general", "why": "x"},
             {"merchant": "amazon", "theme": "beauty-and-personal-care", "why": "x"}]
    enforce_pair_constraints(slots, {"merchants": {"amazon", "flipkart"},
                                     "categories": {"electronics-and-gadgets"}}, FEED)
    assert all(s["merchant"] in {"amazon", "flipkart"} for s in slots), slots
    assert all(s["theme"] == "electronics-and-gadgets" for s in slots), slots


def test_unsatisfiable_combo_reports_and_leaves_slots():
    slots = [{"merchant": "amazon", "theme": "electronics-and-gadgets", "why": "x"}]
    note = enforce_pair_constraints(slots, {"merchants": {"myntra"},
                                            "categories": {"electronics-and-gadgets"}}, FEED)
    assert note and "no deals matching" in note[0]
    assert slots[0]["merchant"] == "amazon"  # left as-is, not silently faked


def test_place_in_window_all_inside_unique_sorted_offgrid():
    slots = [{"type": "single", "merchant": "amazon", "theme": "t"} for _ in range(38)]
    out = _place_in_window(slots, 18 * 60, 24 * 60 - 1)  # evening only
    mins = [_slot_minute(s) for s in out]
    assert all(18 * 60 <= m <= 24 * 60 - 1 for m in mins)      # inside the window
    assert mins == sorted(mins) and len(set(mins)) == len(mins)  # ordered + unique
    assert not any(m % 5 == 0 for m in mins)                    # off the round grid
    # deterministic — same slots produce the same schedule on re-run
    again = _place_in_window([{"type": "single", "merchant": "amazon", "theme": "t"} for _ in range(38)],
                             18 * 60, 24 * 60 - 1)
    assert [s["time_ist"] for s in out] == [s["time_ist"] for s in again]