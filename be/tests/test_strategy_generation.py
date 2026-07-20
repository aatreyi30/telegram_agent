"""Strategy-compliance tests — emoji policy enforcement + strategy-aware selection.

Covers the operator's core complaint: posts must FOLLOW the strategy (no avoid-emoji,
content-mix respected) and explain themselves.
"""

from __future__ import annotations

from src.services.generation.strategy import EmojiRule, PostingStrategy


def _strategy():
    rules = [
        EmojiRule("👉", 145.6, 37.9, 15.4, 408),
        EmojiRule("🔥", 32.5, 20.4, 15.4, 3508),
        EmojiRule("😍", -40.0, 9.2, 15.4, 3455),
        EmojiRule("✨", -36.4, 9.7, 15.4, 3935),
    ]
    return PostingStrategy(
        content_mix=[{"post_type": "multi-deal", "current_share": 0.03, "action": "increase",
                      "avg_views_per_day": 108.0},
                     {"post_type": "low-price", "current_share": 0.36, "action": "reduce",
                      "avg_views_per_day": 5.0}],
        lead_emojis=["🔥", "🛒", "👉"], avoid_emojis=["😍", "✨"], emoji_rules=rules,
        posting_windows=[{"part": "Afternoon", "hours": "12:00–17:00",
                          "recommended_posts_per_day": 9, "avg_views_per_day": 40.0},
                         {"part": "Morning", "hours": "06:00–11:00",
                          "recommended_posts_per_day": 2, "avg_views_per_day": 12.0}],
        window_desc="owned, last 12.0 mo", available=True)


def test_emoji_rule_note_states_numbers_and_period():
    r = EmojiRule("👉", 145.6, 37.9, 15.4, 408)
    note = r.note("owned, last 12 mo")
    assert "👉" in note and "+146%" in note and "n=408" in note and "owned, last 12 mo" in note
    assert "correlational" in note


def test_strategy_best_window_is_highest_views():
    st = _strategy()
    win = st.best_window()
    assert win["part"] == "Afternoon"          # 40 vpd beats 12 vpd


def test_rationale_collection_cites_numbers_period():
    st = _strategy()
    r = st.rationale("collection")
    assert r["kind"] == "collection"
    assert "108" in r["why_type"] and "owned, last 12.0 mo" in r["why_type"]
    assert r["target_window_ist"]["part"] == "Afternoon"
    assert set(r["emoji_policy"]["avoid"]) == {"😍", "✨"}


def test_rationale_single_notes_the_cap():
    st = _strategy()
    r = st.rationale("single")
    assert "caps low-priced singles" in r["why_type"]


def test_strategy_aware_selector_caps_low_price_singles():
    from types import SimpleNamespace

    from src.services.generation.ranking import StrategyAwareSelector

    # 10 cheap non-loot deals; cap should keep only ~count//5 of them
    deals = [SimpleNamespace(deal_validity="valid", is_loot_deal=False, current_price=99.0,
                             merchant_key=f"m{i}", rank_score=1.0) for i in range(10)]
    chosen = StrategyAwareSelector(_strategy()).select(deals, count=5)
    assert len(chosen) == 1                     # count//5 == 1 budget single allowed
