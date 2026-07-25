"""Per-post planning (AC1/AC4/AC5/AC6 of loops/01-ship/queue/per-post-planning.md).

AC2/AC3 (jit_fill.py's slot expansion + executor honouring per-post intent) are
covered elsewhere — this file only exercises the planner + persist-time
reconciliation, which is what this trip touches.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from src.ai.planner import (
    _MAX_MERCHANT_SHARE,
    _MIN_TYPE_SHARE,
    _fallback_day_plan,
    _feed_pairs,
    _pair_sequence,
    _repair_plan_diversity,
    parse_plan,
)
from src.ai.factcheck import check_cited_numbers, extract_prose_numbers, plan_structural_numbers
from src.services.generation.ai_execution import _rescale_slot_counts


# ── AC1 — per-post plan schema ────────────────────────────────────────────

def test_parse_plan_accepts_per_post_shape_one_object_per_post():
    raw = (
        '{"date":"2026-07-21","recommended_posts":3,"cadence_why":"x",'
        '"post_slots":['
        '{"type":"single","time_ist":"09:05","theme":"electronics",'
        '"merchant":"amazon","max_price":null,"min_price":null,"why":"x"},'
        '{"type":"single","time_ist":"10:40","theme":"fashion",'
        '"merchant":"ajio","max_price":null,"min_price":null,"why":"x"},'
        '{"type":"collection","time_ist":"18:15","theme":"electronics",'
        '"merchant":"amazon","max_price":700,"min_price":null,"why":"x"}'
        '],"emphasis":"e","watch":"w","cited_numbers":[]}'
    )
    plan = parse_plan(raw)
    assert len(plan["post_slots"]) == 3
    times = [sl["time_ist"] for sl in plan["post_slots"]]
    assert times == ["09:05", "10:40", "18:15"]
    # no `count`/`window_ist` on the new shape — each object IS one post.
    assert all("count" not in sl for sl in plan["post_slots"])


def test_parse_plan_still_accepts_legacy_window_shape():
    """AC2's other half (backward compat), verified from the planner side:
    a legacy window_ist+count slot must still parse."""
    raw = (
        '{"date":"2026-07-21","recommended_posts":8,"cadence_why":"x",'
        '"post_slots":[{"type":"single","window_ist":"09:00-12:00","count":5,'
        '"theme":"electronics","merchant":"amazon","why":"x"},'
        '{"type":"collection","window_ist":"18:00-21:00","count":3,'
        '"theme":"fashion","merchant":"ajio","why":"x"}],'
        '"emphasis":"e","watch":"w","cited_numbers":[]}'
    )
    plan = parse_plan(raw)
    assert plan["post_slots"][0]["count"] == 5


# ── AC4 — adjacency repair, both dimensions, chronological ────────────────

def test_repair_breaks_a_run_of_identical_merchants_chronologically():
    slots = [{"time_ist": f"{9 + i // 2:02d}:{(i % 2) * 30:02d}", "merchant": "amazon",
             "theme": "electronics"} for i in range(10)]
    _repair_plan_diversity(slots, ["amazon", "flipkart", "myntra"], None)
    ordered = sorted(slots, key=lambda sl: sl["time_ist"])
    assert all(ordered[i]["merchant"] != ordered[i + 1]["merchant"]
              for i in range(len(ordered) - 1))
    counts = Counter(sl["merchant"] for sl in slots)
    assert counts["amazon"] / len(slots) <= _MAX_MERCHANT_SHARE


def test_repair_breaks_a_run_of_identical_themes_chronologically():
    slots = [{"time_ist": f"{9 + i:02d}:00", "merchant": "amazon", "theme": "electronics"}
            for i in range(4)]
    _repair_plan_diversity(slots, None, ["electronics", "fashion"])
    assert all(slots[i]["theme"] != slots[i + 1]["theme"] for i in range(len(slots) - 1))


def test_repair_no_ops_with_fewer_than_2_available_options():
    slots = [{"time_ist": f"{9 + i:02d}:00", "merchant": "amazon", "theme": "electronics"}
            for i in range(3)]
    _repair_plan_diversity(slots, ["amazon"], ["electronics"])
    assert all(sl["merchant"] == "amazon" and sl["theme"] == "electronics" for sl in slots)


def test_repair_rewrites_why_on_a_reassigned_slot():
    slots = [{"time_ist": "09:00", "merchant": "amazon", "why": "original reasoning"},
             {"time_ist": "09:30", "merchant": "amazon", "why": "original reasoning"}]
    _repair_plan_diversity(slots, ["amazon", "flipkart"], None)
    reassigned = [sl for sl in slots if sl["merchant"] != "amazon"]
    assert reassigned and all("original reasoning" not in sl["why"] for sl in reassigned)


# ── AC5 — count reconciliation over whole slots ────────────────────────────

def test_rescale_per_post_shape_drops_slots_preserving_total_and_order():
    plan = {"post_slots": [
        {"type": "single", "time_ist": f"{9 + i:02d}:00", "merchant": "amazon"}
        for i in range(6)
    ] + [
        {"type": "collection", "time_ist": f"{18 + i:02d}:00", "merchant": "ajio"}
        for i in range(4)
    ]}
    _rescale_slot_counts(plan, 5)
    slots = plan["post_slots"]
    assert len(slots) == 5
    times = [sl["time_ist"] for sl in slots]
    assert times == sorted(times)
    counts = Counter(sl["type"] for sl in slots)
    assert min(counts.values()) / len(slots) >= _MIN_TYPE_SHARE - 1e-9


def test_rescale_per_post_shape_duplicates_slots_to_hit_a_larger_total():
    """S1-d — the reviewer's exact repro: 2 slots reconciled up to 7 must NOT
    dump duplicates of the last slot at (near-)identical times/merchant/theme
    (the reported "one brand, dumped all at once" defect). Every fire time
    stays distinct and no chronologically-adjacent pair repeats merchant or
    theme."""
    plan = {"post_slots": [
        {"type": "single", "time_ist": "09:00", "merchant": "amazon", "theme": "electronics"},
        {"type": "collection", "time_ist": "18:00", "merchant": "ajio", "theme": "fashion"},
    ]}
    _rescale_slot_counts(plan, 7)
    slots = plan["post_slots"]
    assert len(slots) == 7
    times = [sl["time_ist"] for sl in slots]
    assert times == sorted(times), times
    assert len(set(times)) == len(times), times  # every fire time distinct — no burst
    for i in range(len(slots) - 1):
        assert slots[i]["merchant"] != slots[i + 1]["merchant"], slots
        assert slots[i]["theme"] != slots[i + 1]["theme"], slots


def test_rescale_duplicate_why_never_names_a_different_merchant():
    """S2-3 — a duplicate whose merchant/theme got rotated away from the source
    slot must not keep the source's grounded `why` (written for the OLD
    merchant/theme) verbatim-plus-suffix: that reads as a stat about one
    merchant attached to a different merchant's post. Reviewer's exact repro:
    2 slots reconciled up to 7."""
    plan = {"post_slots": [
        {"type": "single", "time_ist": "09:00", "merchant": "amazon", "theme": "electronics",
         "why": "grounded stat: amazon 0.31 share of electronics posts this week"},
        {"type": "collection", "time_ist": "18:00", "merchant": "ajio", "theme": "fashion",
         "why": "grounded stat: ajio 0.19 share of fashion posts this week"},
    ]}
    _rescale_slot_counts(plan, 7)
    slots = plan["post_slots"]
    assert len(slots) == 7
    merchants = {"amazon", "ajio"}
    for sl in slots:
        why = (sl.get("why") or "").lower()
        other_merchants = merchants - {sl["merchant"]}
        for other in other_merchants:
            assert other not in why, (sl["merchant"], sl["why"])


def test_rescale_never_reduces_the_day_to_zero_posts():
    plan = {"post_slots": [{"type": "single", "time_ist": "09:00", "merchant": "amazon"}]}
    _rescale_slot_counts(plan, 0)
    assert len(plan["post_slots"]) >= 1


def test_rescale_legacy_shape_still_scales_the_count_field():
    plan = {"post_slots": [{"type": "single", "window_ist": "09:00-12:00", "count": 6},
                           {"type": "collection", "window_ist": "18:00-21:00", "count": 3}]}
    _rescale_slot_counts(plan, 6)
    assert sum(sl["count"] for sl in plan["post_slots"]) == 6


# ── AC6 — fallback plan matches the new per-post shape ─────────────────────

def test_fallback_plan_emits_per_post_shape_spread_and_mixed():
    ctx = {
        "posting_windows": [{"part": "morning", "hours": "09:00-12:00", "posts": 4},
                            {"part": "evening", "hours": "18:00-21:00", "posts": 4}],
        "merchant_mix": [{"merchant": "amazon"}, {"merchant": "flipkart"}],
        "available_merchants": ["amazon", "flipkart"],
        "available_categories": ["electronics", "fashion"],
        "recommended_posts": 8,
        "this_week_direction": {"loot_deal_ratio": {"loot": 4, "deal": 6}},
    }
    fb = _fallback_day_plan(date.fromisoformat("2026-07-21"), ctx)
    assert fb["is_fallback"] is True
    slots = fb["post_slots"]
    assert len(slots) == 8
    assert all("count" not in sl and "time_ist" in sl for sl in slots)
    assert {sl["type"] for sl in slots} == {"single", "collection"}
    # spread, not bunched: not every post shares one minute.
    assert len({sl["time_ist"] for sl in slots}) >= 2


def test_fallback_plan_never_empty_even_with_no_windows_or_merchants():
    fb = _fallback_day_plan(date.fromisoformat("2026-07-21"), {"recommended_posts": 3})
    assert len(fb["post_slots"]) >= 1


# ── merchant/category pairing sourced from the real feed (deal-dimension fix) ──

def _cross_tab_available_deals() -> list[dict]:
    """Synthetic ``available_deals`` matching the live cross-tab in the spec —
    a merchant/category cell appears N times to encode its deal count."""
    counts = {
        ("ajio", "beauty"): 2, ("ajio", "electronics"): 4, ("ajio", "fashion"): 77,
        ("ajio", "general"): 2, ("ajio", "health"): 1, ("ajio", "home"): 1,
        ("amazon", "beauty"): 1, ("amazon", "electronics"): 28, ("amazon", "fashion"): 9,
        ("amazon", "general"): 14, ("amazon", "home"): 5,
        ("flipkart", "beauty"): 1, ("flipkart", "electronics"): 28, ("flipkart", "fashion"): 16,
        ("flipkart", "general"): 19, ("flipkart", "home"): 2,
        ("myntra", "beauty"): 2, ("myntra", "fashion"): 21, ("myntra", "home"): 1,
    }
    deals = []
    for (merchant, category), n in counts.items():
        for _ in range(n):
            deals.append({"merchant_key": merchant, "category": category})
    return deals


def _cross_tab_ctx(recommended_posts: int = 12) -> dict:
    deals = _cross_tab_available_deals()
    return {
        "posting_windows": [{"part": "all day", "hours": "09:00-21:00", "posts": recommended_posts}],
        "available_merchants": sorted({d["merchant_key"] for d in deals}),
        "available_categories": sorted({d["category"] for d in deals}),
        "available_deals": deals,
        "recommended_posts": recommended_posts,
        "this_week_direction": {"loot_deal_ratio": {"loot": 4, "deal": 6}},
    }


def test_fallback_plan_never_pairs_a_merchant_with_a_category_it_does_not_stock():
    fb = _fallback_day_plan(date.fromisoformat("2026-07-21"), _cross_tab_ctx())
    pairs = {(sl["merchant"], sl["theme"]) for sl in fb["post_slots"]}
    assert ("myntra", "electronics") not in pairs, pairs


def test_fallback_plan_gives_one_merchant_multiple_categories_across_the_day():
    fb = _fallback_day_plan(date.fromisoformat("2026-07-21"), _cross_tab_ctx())
    by_merchant: dict[str, set] = {}
    for sl in fb["post_slots"]:
        by_merchant.setdefault(sl["merchant"], set()).add(sl["theme"])
    assert any(len(cats) >= 2 for cats in by_merchant.values()), by_merchant


def test_fallback_plan_merchant_and_category_cycles_are_not_locked_in_lockstep():
    fb = _fallback_day_plan(date.fromisoformat("2026-07-21"), _cross_tab_ctx())
    merchants = {sl["merchant"] for sl in fb["post_slots"]}
    categories = {sl["theme"] for sl in fb["post_slots"]}
    distinct_pairs = {(sl["merchant"], sl["theme"]) for sl in fb["post_slots"]}
    assert len(distinct_pairs) > max(len(merchants), len(categories)), (distinct_pairs, merchants, categories)


def test_fallback_plan_breaks_lockstep_even_without_available_deals():
    """Degrade path: no available_deals at all — still must not tie the merchant
    and category cycles to the same index (the original defect: with equal-length
    lists and both cycles at ``post_idx % len``, only 4 distinct pairs are ever
    possible across a 12-post day instead of up to 16)."""
    ctx = {
        "posting_windows": [{"part": "all day", "hours": "09:00-21:00", "posts": 12}],
        "available_merchants": ["amazon", "flipkart", "myntra", "ajio"],
        "available_categories": ["electronics", "home", "fashion", "beauty"],
        "recommended_posts": 12,
    }
    fb = _fallback_day_plan(date.fromisoformat("2026-07-21"), ctx)
    pairs = [(sl["merchant"], sl["theme"]) for sl in fb["post_slots"]]
    assert len(fb["post_slots"]) == 12
    distinct_pairs = set(pairs)
    assert len(distinct_pairs) > 4, distinct_pairs


def test_repair_plan_diversity_never_reassigns_to_an_unavailable_pairing():
    slots = [
        {"time_ist": "09:00", "merchant": "flipkart", "theme": "electronics-and-gadgets"},
        {"time_ist": "09:30", "merchant": "flipkart", "theme": "electronics-and-gadgets"},
        {"time_ist": "10:00", "merchant": "flipkart", "theme": "electronics-and-gadgets"},
    ]
    available_pairs = {("flipkart", "electronics-and-gadgets"), ("amazon", "electronics-and-gadgets"),
                        ("myntra", "fashion")}
    _repair_plan_diversity(slots, ["flipkart", "amazon", "myntra"],
                           ["electronics-and-gadgets", "fashion"],
                           available_pairs=available_pairs)
    for sl in slots:
        assert (sl["merchant"], sl["theme"]) in available_pairs, slots
    ordered = sorted(slots, key=lambda sl: sl["time_ist"])
    assert any(ordered[i]["merchant"] != ordered[i + 1]["merchant"]
              for i in range(len(ordered) - 1)), "run of identical merchants was not broken"


# ── S2-a — factcheck whitelists a per-post slot's own time_ist ─────────────

def test_repair_plan_diversity_swaps_the_whole_pair_when_only_two_valid_pairs_exist():
    """Only a both-dimensions swap can break this adjacency run: with just two
    valid pairs that differ in BOTH merchant and theme, changing merchant alone
    (or theme alone) always lands outside available_pairs, so a single-dimension
    move is impossible — the repair must reassign the whole (merchant, theme)
    pair together."""
    slots = [
        {"time_ist": "09:00", "merchant": "amazon", "theme": "electronics"},
        {"time_ist": "09:30", "merchant": "amazon", "theme": "electronics"},
        {"time_ist": "10:00", "merchant": "amazon", "theme": "electronics"},
        {"time_ist": "10:30", "merchant": "amazon", "theme": "electronics"},
    ]
    available_pairs = {("amazon", "electronics"), ("flipkart", "home")}
    _repair_plan_diversity(slots, ["amazon", "flipkart"], ["electronics", "home"],
                           available_pairs=available_pairs)
    for sl in slots:
        assert (sl["merchant"], sl["theme"]) in available_pairs, slots
    ordered = sorted(slots, key=lambda sl: sl["time_ist"])
    assert all(ordered[i]["merchant"] != ordered[i + 1]["merchant"]
              for i in range(len(ordered) - 1)), ordered
    assert all(ordered[i]["theme"] != ordered[i + 1]["theme"]
              for i in range(len(ordered) - 1)), ordered


def test_repair_plan_diversity_leaves_a_stranded_slot_untouched():
    """No valid alternative pair exists at all for the second slot (the only
    other available pair uses a merchant/theme this slot can't reach without
    landing outside available_pairs) — it must be left as-is rather than
    forced onto an invalid combination."""
    slots = [
        {"time_ist": "09:00", "merchant": "amazon", "theme": "electronics"},
        {"time_ist": "09:30", "merchant": "amazon", "theme": "electronics"},
    ]
    # The only other pair in the set doesn't help: swapping to it would still
    # collide with itself being the sole alternative (no third option to rotate
    # through), so the second slot's adjacency violation can't be cleared —
    # available_pairs has only ONE usable pair once (amazon, electronics) is
    # excluded, and it's still needed too, verified by the closed 2-slot case
    # above; here we truly have only one valid pair to work with at all.
    available_pairs = {("amazon", "electronics")}
    _repair_plan_diversity(slots, ["amazon", "flipkart"], ["electronics", "home"],
                           available_pairs=available_pairs)
    assert all(sl["merchant"] == "amazon" and sl["theme"] == "electronics" for sl in slots)


def test_why_quoting_its_own_time_ist_factchecks_passed():
    """The prompt requires each `why` to justify its own timing — restating
    the slot's own scheduled hour/minute must never read as a fabrication."""
    plan = {"post_slots": [
        {"type": "single", "time_ist": "09:05", "merchant": "amazon",
         "theme": "electronics", "why": "posting at 09:05 to catch morning scroll"},
    ]}
    prose = extract_prose_numbers(plan)
    structural = plan_structural_numbers(plan)
    assert {9.0, 5.0} <= set(structural), structural
    fc = check_cited_numbers(prose, [{"s": v} for v in structural])
    assert fc["status"] == "passed", fc


def test_reconciliation_leaves_no_adjacent_repeat_across_type_groups():
    """Each type is reconciled independently and the groups are then interleaved by the
    final chronological sort — so two slots from DIFFERENT type groups could land adjacent
    with the same merchant even though neither group repeated internally. Reproduces the
    reviewer's 2-slots-padded-to-7 case, which left 2 adjacent same-merchant pairs."""
    from src.services.generation.ai_execution import _rescale_slot_counts

    plan = {"post_slots": [
        {"type": "collection", "time_ist": "09:00", "merchant": "amazon",
         "theme": "electronics-and-gadgets", "why": "w"},
        {"type": "single", "time_ist": "10:00", "merchant": "flipkart",
         "theme": "home-and-living", "why": "w"},
    ]}
    _rescale_slot_counts(plan, 7)
    slots = plan["post_slots"]

    assert len(slots) == 7, slots
    assert len({s["time_ist"] for s in slots}) == 7, [s["time_ist"] for s in slots]
    times = [s["time_ist"] for s in slots]
    assert times == sorted(times), times                      # chronological
    pairs = list(zip(slots, slots[1:]))
    assert not [a for a, b in pairs if a["merchant"] == b["merchant"]], times
    assert not [a for a, b in pairs if a["theme"] == b["theme"]], times


# --------------------------------------------------------------------------- #
# Seam fixes found by running the composed pipeline, not by reading either half.
# --------------------------------------------------------------------------- #

_FEED_XTAB = [  # live be/data/tgagent.db cross-tab (merchant, category, deal count)
    ("ajio", "beauty-and-personal-care", 2), ("ajio", "electronics-and-gadgets", 4),
    ("ajio", "fashion-and-lifestyle", 77), ("ajio", "general", 2), ("ajio", "home-and-living", 1),
    ("amazon", "beauty-and-personal-care", 1), ("amazon", "electronics-and-gadgets", 28),
    ("amazon", "fashion-and-lifestyle", 9), ("amazon", "general", 14), ("amazon", "home-and-living", 5),
    ("flipkart", "beauty-and-personal-care", 1), ("flipkart", "electronics-and-gadgets", 28),
    ("flipkart", "fashion-and-lifestyle", 16), ("flipkart", "general", 19), ("flipkart", "home-and-living", 2),
    ("myntra", "beauty-and-personal-care", 2), ("myntra", "fashion-and-lifestyle", 21),
    ("myntra", "home-and-living", 1),
]


def _feed_ctx():
    return {
        "posting_windows": [{"part": "m", "hours": "09:00-12:00", "posts": 4},
                            {"part": "a", "hours": "13:00-17:00", "posts": 4},
                            {"part": "e", "hours": "19:00-23:00", "posts": 4}],
        "merchant_mix": [{"merchant": m} for m in ["amazon", "flipkart", "myntra", "ajio"]],
        "available_merchants": ["amazon", "flipkart", "myntra", "ajio"],
        "available_categories": ["electronics-and-gadgets", "home-and-living",
                                 "fashion-and-lifestyle", "beauty-and-personal-care", "general"],
        "available_deals": [{"merchant_key": m, "category": c}
                            for m, c, n in _FEED_XTAB for _ in range(n)],
        "recommended_posts": 12,
    }


def test_fallback_plan_repairs_theme_adjacency_too():
    """Both fallback returns in generate_day_plan hand the plan straight back WITHOUT
    running the adjacency repair the AI path runs after parsing — so an AI outage was the
    one day nothing fixed adjacency. The pair walk rotates merchants cleanly but left 4
    adjacent same-theme pairs across a 12-post day."""
    from src.ai.planner import _fallback_day_plan

    slots = _fallback_day_plan(date(2026, 7, 25), _feed_ctx())["post_slots"]
    pairs = list(zip(slots, slots[1:]))
    assert not [a for a, b in pairs if a["merchant"] == b["merchant"]]
    assert not [a for a, b in pairs if a["theme"] == b["theme"]]


def test_reconciliation_repair_cannot_invent_an_unstocked_pairing():
    """`_reconcile_per_post_slots` passed only the flat merchant/theme pools to the repair,
    which lets it recombine them freely — e.g. onto myntra+electronics, which the feed
    stocks ZERO of. An unfillable slot falls through jit_fill's broadening tiers, which is
    the one-merchant-window defect re-entering a layer up."""
    from src.ai.planner import _fallback_day_plan
    from src.services.generation.ai_execution import _rescale_slot_counts

    valid = {(m, c) for m, c, _ in _FEED_XTAB}
    plan = {"post_slots": _fallback_day_plan(date(2026, 7, 25), _feed_ctx())["post_slots"]}
    for target in (5, 9, 17, 23):
        p = {"post_slots": [dict(s) for s in plan["post_slots"]]}
        _rescale_slot_counts(p, target)
        got = {(s["merchant"], s["theme"]) for s in p["post_slots"]
               if s.get("merchant") and s.get("theme")}
        assert not (got - valid), (target, got - valid)
        assert len(p["post_slots"]) == target


# ── S1-1/S1-2 (deal-dimension intelligence trip 4) — stock-aware pairing ──────

_SPARSE_FEED = [  # <=8 valid pairs — free recombination can't land valid "by luck"
    ("amazon", "electronics-and-gadgets", 5), ("amazon", "general", 3),
    ("flipkart", "electronics-and-gadgets", 4), ("flipkart", "home-and-living", 2),
    ("myntra", "fashion-and-lifestyle", 6), ("ajio", "fashion-and-lifestyle", 3),
    ("ajio", "beauty-and-personal-care", 1),
]


def _sparse_ctx(recommended_posts: int = 7) -> dict:
    deals = [{"merchant_key": m, "category": c} for m, c, n in _SPARSE_FEED for _ in range(n)]
    return {
        "posting_windows": [{"part": "all day", "hours": "09:00-21:00", "posts": recommended_posts}],
        "available_merchants": sorted({m for m, _, _ in _SPARSE_FEED}),
        "available_categories": sorted({c for _, c, _ in _SPARSE_FEED}),
        "available_deals": deals,
        "recommended_posts": recommended_posts,
        "this_week_direction": {"loot_deal_ratio": {"loot": 4, "deal": 6}},
    }


def test_reconciliation_on_a_sparse_feed_never_invents_an_unstocked_pairing():
    """S1-1, reproduced sparse (only 7 valid pairs — the 18-of-20-pair feed above lets
    the old defect (two independent merchant/theme pools) land valid by luck; this
    feed is sparse enough that it can't). Targets well above the slot count (23, 31)
    force heavy duplication, which is exactly where the old code invented pairings
    (e.g. a rotated-in merchant crossed with a rotated-in theme that together the
    feed stocks zero of)."""
    valid = {(m, c) for m, c, _ in _SPARSE_FEED}
    ctx = _sparse_ctx()
    feed_pairs = _feed_pairs(ctx["available_deals"])
    base = _fallback_day_plan(date(2026, 7, 25), ctx)["post_slots"]
    for target in (23, 31):
        p = {"post_slots": [dict(s) for s in base]}
        _rescale_slot_counts(p, target, feed_pairs)
        got = {(s["merchant"], s["theme"]) for s in p["post_slots"]
               if s.get("merchant") and s.get("theme")}
        assert not (got - valid), (target, got - valid)
        assert len(p["post_slots"]) == target


def test_fallback_plan_never_exceeds_a_pairings_stock_on_the_live_cross_tab():
    """S1-2 — a slot must not be scheduled onto a pairing the feed can't sustain: no
    (merchant, theme) pairing may get more slots than it has deals in the feed.
    BLOCKED.md's exact repro (single all-day window, 12 posts, ``_cross_tab_ctx``):
    3 slots landed on amazon+beauty, which has exactly 1 deal in the whole feed."""
    deals = _cross_tab_available_deals()
    stock: dict[tuple[str, str], int] = {}
    for d in deals:
        stock[(d["merchant_key"], d["category"])] = stock.get((d["merchant_key"], d["category"]), 0) + 1
    fb = _fallback_day_plan(date(2026, 7, 25), _cross_tab_ctx())
    used = Counter((sl["merchant"], sl["theme"]) for sl in fb["post_slots"])
    for pair, n in used.items():
        assert n <= stock.get(pair, 0), (pair, n, stock.get(pair, 0))


def test_pair_sequence_orders_by_stock_depth_not_alphabetically():
    """`_pair_sequence` must visit deeper-stocked merchants/categories first — a
    round-robin cycle in alphabetical order instead would put a near-empty pairing
    (e.g. amazon+beauty, 1 deal) into circulation just as early as a 77-deal one."""
    counts = {("flipkart", "electronics"): 50, ("ajio", "electronics"): 2}
    seq = _pair_sequence(counts)
    assert seq[0] == ("flipkart", "electronics"), seq  # deepest first, not alphabetical ('ajio' < 'flipkart')


def test_repair_plan_diversity_honours_the_merchant_cap_on_the_available_pairs_path():
    """S3-1 — `cands = capped or cands` in the whole-pair-swap branch let a merchant
    exceed `_MAX_MERCHANT_SHARE` (50% observed vs a 40% cap) even when a compliant
    assignment existed elsewhere in `available_pairs`; only the `None` path had a
    cap test before this."""
    slots = [{"time_ist": f"{9 + i:02d}:00", "merchant": "amazon", "theme": "electronics"}
             for i in range(5)]
    available_pairs = {("amazon", "electronics"), ("flipkart", "electronics"),
                        ("flipkart", "home"), ("myntra", "fashion")}
    _repair_plan_diversity(slots, ["amazon", "flipkart", "myntra"],
                           ["electronics", "home", "fashion"], available_pairs=available_pairs)
    cap = max(round(len(slots) * _MAX_MERCHANT_SHARE), 1)
    counts = Counter(sl["merchant"] for sl in slots)
    assert all(v <= cap for v in counts.values()), counts
    for sl in slots:
        assert (sl["merchant"], sl["theme"]) in available_pairs, slots
