"""Slot `type` -> loot-vs-single routing.

The daily plan's `type` is LLM-written and drifts off the prompt's "single|collection"
vocabulary. A loot type the code fails to recognise does NOT error — it quietly builds a
single-product post, so the loot format never renders and nothing says why. These pin the
values really observed from gpt-4o-mini in plan#5/#6.
"""

from __future__ import annotations

import pytest

from src.services.generation.constants import is_loot_type


@pytest.mark.parametrize("slot_type", [
    "collection",           # the prompt's own vocabulary
    "loot",
    "category_collection",
    "loot_deal",            # OBSERVED from gpt-4o-mini (plan#5) — used to route to single
    "Loot_Deal",            # casing must not matter
    "multi_deal_collection",
    "loot / multi-deal",
])
def test_loot_types_route_to_the_loot_builder(slot_type):
    assert is_loot_type(slot_type) is True


@pytest.mark.parametrize("slot_type", [
    "single",
    "single_deal",          # OBSERVED from gpt-4o-mini (plan#5)
    "SINGLE",
    "deal",
    "product",
    "",
    None,
])
def test_single_types_do_not_route_to_loot(slot_type):
    assert is_loot_type(slot_type) is False


def test_jit_fill_and_copywriter_agree():
    """Both modules decide loot-ness independently — jit_fill picks the builder, the
    copywriter picks the exemplar. If they ever disagree, a loot post gets written
    against the single-deal format reference (or vice versa)."""
    from src.ai.copywriter import _exemplar
    from src.services.generation.jit_fill import _is_loot_type

    tpl = {"single_loot_badge": "SINGLE_MARKER", "loot_theme_default": "LOOT_MARKER"}
    for slot_type in ("loot_deal", "collection", "single", "single_deal"):
        loot = _is_loot_type(slot_type)
        exemplar = _exemplar(slot_type, tpl)
        expected = "LOOT_MARKER" if loot else "SINGLE_MARKER"
        assert expected in exemplar, (slot_type, loot, exemplar)
