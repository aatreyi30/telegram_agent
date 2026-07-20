"""Post-style rotation — the antidote to "every post looks the same".

A single-deal post used to be ONE fixed skeleton (hook / name / discount / price /
coupon / cta, always joined by a blank line). Different words, identical shape, so a
channel of them read as one template on repeat.

Each Style here pairs:
  * a TONE directive (appended to the copywriter prompt) — varies hook flavour, energy
    and emoji palette, so the WORDS differ; and
  * a LAYOUT (how the model's parsed sections are arranged) — varies the SHAPE and
    spacing, so the posts don't line up block-for-block.

The model still returns the same safe tagged sections; only how they're arranged and
what tone they're written in changes. Rotating styles per post (see jit_fill) makes
consecutive posts look and read differently. Deterministic: variant N -> STYLES[N % len].
"""

from __future__ import annotations

# ---- layout specs -----------------------------------------------------------------
# A layout is a list of `lines`; each line is a list of section keys joined by `join`;
# lines are joined by `gap`. A missing/blank section is dropped, and a line with no
# surviving sections disappears (so optional discount/price/coupon never leave a hole).
# Section keys come from copywriter._TAG_ORDER: hook, name, discount, price, coupon, cta.

_L_BLOCKS = {"lines": [["hook"], ["name"], ["discount"], ["price"], ["coupon"], ["cta"]],
             "join": " ", "gap": "\n\n"}
_L_PRICELINE = {"lines": [["hook"], ["name"], ["discount", "price"], ["coupon"], ["cta"]],
                "join": " · ", "gap": "\n\n"}
_L_HEADLINE = {"lines": [["hook"], ["name", "discount"], ["price"], ["coupon"], ["cta"]],
               "join": "  ", "gap": "\n\n"}
_L_TIGHT = {"lines": [["hook"], ["name"], ["discount", "price"], ["coupon"], ["cta"]],
            "join": " · ", "gap": "\n"}
_L_SPOTLIGHT = {"lines": [["discount"], ["name"], ["price"], ["coupon"], ["cta"]],
                "join": " ", "gap": "\n\n"}

DEFAULT_LAYOUT = _L_BLOCKS  # the channel's known-good "separate blocks" look


def render_layout(tags: dict, spec: dict | None = None) -> str:
    """Arrange the parsed section tags per `spec`, dropping blanks. Pure/testable."""
    spec = spec or DEFAULT_LAYOUT
    out: list[str] = []
    for line in spec["lines"]:
        parts = [tags[k].strip() for k in line if (tags.get(k) or "").strip()]
        if parts:
            out.append(spec.get("join", " ").join(parts))
    return spec.get("gap", "\n\n").join(out)


# ---- styles (tone directive + layout) ---------------------------------------------

class Style:
    __slots__ = ("key", "tone", "layout")

    def __init__(self, key: str, tone: str, layout: dict):
        self.key, self.tone, self.layout = key, tone, layout


STYLES: list[Style] = [
    Style(
        "classic",
        "STYLE — Urgency. High energy. Open the hook with a punchy emoji (🔥/🚨/⚡) and "
        "put one on the discount line too — 2-3 emoji total, never stacked ('🔥😍').",
        _L_BLOCKS),
    Style(
        "compact",
        "STYLE — Punchy. Crisp and confident, minimal words. Hook is a 3-5 word jolt "
        "with one emoji ('⚡ Steal of the day'). 1-2 emoji total.",
        _L_PRICELINE),
    Style(
        "curious",
        "STYLE — Curiosity. Hook is a question aimed at the shopper ('Upgrading your "
        "kitchen?', 'Trip coming up?'). Calm, aspirational. 0-1 emoji total — stay clean.",
        _L_HEADLINE),
    Style(
        "value",
        "STYLE — Value. Lead the reader to the saving; frame it as the smart buy. Warm, "
        "plain-spoken, no hype. Exactly 1 emoji, near the price (💰/🤑).",
        _L_TIGHT),
    Style(
        "bold",
        "STYLE — Bold. Lead with the deal itself; the discount is the opener. Confident and "
        "playful. Put an emoji on the discount (💥/🤑) and the hook-less opener pops — "
        "2-3 emoji total, never stacked.",
        _L_SPOTLIGHT),
]


def pick_style(variant: int) -> Style:
    return STYLES[variant % len(STYLES)]


# ---- loot theme flavours (lighter touch — loot posts already vary by category) -----

LOOT_FLAVORS: list[str] = [
    "THEME FLAVOUR — Mega/loot energy: a big, exciting board banner ('Mega Fashion Loot').",
    "THEME FLAVOUR — Steal-alert: frame it as a heads-up ('Steal Alert', 'Don't scroll past').",
    "THEME FLAVOUR — Seasonal/occasion: tie the banner to the moment ('Monsoon Essentials').",
    "THEME FLAVOUR — Curated edit: calm, hand-picked feel ('Today's Best Picks').",
]


def pick_loot_flavor(variant: int) -> str:
    return LOOT_FLAVORS[variant % len(LOOT_FLAVORS)]


def _selfcheck() -> None:
    # optional sections drop cleanly, no empty lines/holes left behind
    full = {"hook": "H", "name": "N", "discount": "84% OFF", "price": "₹99", "coupon": "C", "cta": "👉 <link/>"}
    assert render_layout(full, _L_BLOCKS) == "H\n\nN\n\n84% OFF\n\n₹99\n\nC\n\n👉 <link/>"
    assert render_layout(full, _L_PRICELINE) == "H\n\nN\n\n84% OFF · ₹99\n\nC\n\n👉 <link/>"
    assert render_layout(full, _L_TIGHT) == "H\nN\n84% OFF · ₹99\nC\n👉 <link/>"
    # missing discount+coupon must not leave a blank line or a dangling separator
    partial = {"hook": "H", "name": "N", "price": "₹99", "cta": "👉 <link/>"}
    assert render_layout(partial, _L_PRICELINE) == "H\n\nN\n\n₹99\n\n👉 <link/>", render_layout(partial, _L_PRICELINE)
    assert render_layout(partial, _L_SPOTLIGHT) == "N\n\n₹99\n\n👉 <link/>", render_layout(partial, _L_SPOTLIGHT)
    # rotation cycles and is stable
    assert pick_style(0).key == "classic" and pick_style(5).key == "classic"
    assert len({pick_style(i).key for i in range(len(STYLES))}) == len(STYLES)
    print("post_styles selfcheck ok")


if __name__ == "__main__":
    _selfcheck()
