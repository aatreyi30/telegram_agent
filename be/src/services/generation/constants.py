"""Shared literal vocabularies for the generation + copywriting layer.

A pure leaf module (no intra-app imports) so any module in the partition can
reference these without risking an import cycle. Only genuinely REPEATED,
semantically-meaningful vocabularies live here — not one-off literals.
"""

from __future__ import annotations

# Substrings marking a slot/post `type` as "a bundled multi-category loot post" (as
# opposed to a single-product deal).
LOOT_TYPE_MARKERS = ("loot", "collection")


def is_loot_type(slot_type: str | None) -> bool:
    """True when a plan slot's ``type`` means a bundled multi-category loot board.

    Substring match, not an enum, and deliberately so: the daily plan's ``type`` is
    written by an LLM that drifts off the prompt's "single|collection" vocabulary
    ("loot_deal", "single_deal" observed from gpt-4o-mini). An unrecognised loot type
    fails SILENTLY — the slot just builds a single-product post — so a strict list
    turns model drift into invisible wrong output. Loose matching fails safe: the
    worst case is a single-ish type containing "loot" building a loot board, which is
    at least visible.
    """
    t = (slot_type or "").lower()
    return any(m in t for m in LOOT_TYPE_MARKERS)

# Candidate keys, in priority order, for a raw deal item's live price. The FIRST
# present, non-null key wins — order is load-bearing, do not reorder.
PRICE_FIELD_ALIASES = ("discount_price", "scraped_price", "price", "current_price", "sale_price")
