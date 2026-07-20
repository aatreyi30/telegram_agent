"""AI copywriter for single-product deal posts.

The model writes creative copy but returns XML section tags with a `<link/>`
placeholder; this module assembles them with fixed blank-line spacing and swaps
`<link/>` for the finalized tracked link. The model never writes a URL, so the link
is always correct and the layout can't be mangled.
"""

from __future__ import annotations

import json
import re

from sqlalchemy import select

from src.ai.client import AIClient
from src.ai.context import channel_style, to_json
from src.ai.prompts import COPYWRITER_INSTRUCTIONS as _INSTRUCTIONS
from src.ai.prompts import LOOT_INSTRUCTIONS as _LOOT_INSTRUCTIONS
from src.ai.post_styles import render_layout, pick_style, pick_loot_flavor
from src.db.models_generation import EnrichedDeal
from src.db.session import session_scope
from src.services.generation.constants import is_loot_type
from src.services.generation.formatting import _fmt_price

_DEAL_KEYS = ("single_loot_badge", "single_price", "single_coupon_line")
_LOOT_KEYS = ("loot_theme_default", "loot_item", "footer")

_LINK_TOKEN = "<link/>"
_LINK_TOKEN_RE = re.compile(r"<\s*link\s*/?\s*>|\{\{?\s*link\s*\}?\}|\[link\]", re.IGNORECASE)
# Loot posts carry several links: the model writes <LINK_1>, <LINK_2>, ... and we swap
# each for the finalized link at that index.
_LOOT_LINK_RE = re.compile(r"<\s*link[_\s]*(\d+)\s*/?\s*>", re.IGNORECASE)
_TAG_ORDER = ("hook", "name", "discount", "price", "coupon", "cta")


def _product_from_deal(deal: EnrichedDeal) -> dict:
    """PRODUCT facts for the prompt. Link is the `<link/>` token (never the real URL);
    prices are pre-formatted so the model echoes '₹1,099', not '1099.0'."""
    product = {
        "title": deal.title, "merchant": deal.merchant_key,
        "current_price": _fmt_price(deal.current_price), "mrp": _fmt_price(deal.original_price),
        "discount_percent": deal.discount_percent,
        "is_loot_deal": deal.is_loot_deal, "coupon": None,
        "link": _LINK_TOKEN, "category": deal.category,
    }
    for t in (deal.tags or []):
        if isinstance(t, str) and t.startswith("coupon:"):
            product["coupon"] = t.split(":", 1)[1]
    return product


def _parse_examples(raw) -> list[str]:
    """The operator's extra example posts (Settings stores them as a JSON string list
    under _deal_examples/_loot_examples). Tolerant of bad/missing data."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return []
    return [x for x in parsed if isinstance(x, str) and x.strip()] if isinstance(parsed, list) else []


def _exemplar(slot_type: str | None, templates: dict | None) -> str:
    """The channel's winning post shape for this slot type, as a format reference.
    Prefers the operator's full example posts (_deal_examples) when present, else the
    primary template fragments."""
    templates = templates or {}
    loot = is_loot_type(slot_type)
    examples = _parse_examples(templates.get("_loot_examples" if loot else "_deal_examples"))
    if examples:
        return "\n\n---\n\n".join(examples)
    lines = [str(templates[k]) for k in (_LOOT_KEYS if loot else _DEAL_KEYS) if templates.get(k)]
    return "\n\n".join(lines)


def _build_prompt(product: dict, slot: dict | None, exemplar: str, style: dict) -> str:
    slot = slot or {}
    plan_context = {k: slot.get(k) for k in ("theme", "merchant", "type", "why") if slot.get(k)}
    parts = [f"PRODUCT:\n{to_json(product)}"]
    if exemplar:
        parts.append(f"FORMAT_REFERENCE (imitate the shape/tone, do NOT fill literally):\n{exemplar}")
    if plan_context:
        parts.append(f"PLAN_CONTEXT:\n{to_json(plan_context)}")
    parts.append(f"CHANNEL_STYLE:\n{to_json(style)}")
    return "\n\n".join(parts)


# Models write an HTML line break inside a tag instead of a real newline; Telegram has
# no HTML in plain text mode, so it renders the literal "<br>" to the channel.
_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)

# The prompt's output spec writes "<cta>...<link/>...</cta>", where "..." means "your
# text here". gpt-4o-mini copies the ellipsis literally, gluing it to the end of the
# URL ("https://grbn.in/abc..."), which Telegram may swallow into the link. Strip dots
# that trail a URL — a real CTA never ends its link in "..".
_URL_TRAILING_DOTS = re.compile(r"(https?://[^\s]*?[^\s.])\.{2,}(?=\s|$)")


def _clean(s: str) -> str:
    """Model tics that must never reach Telegram, stripped deterministically here
    because every AI post text funnels through. Prompting alone doesn't hold — the
    model reaches for markdown/HTML line-break idioms that Telegram has no notion of:
      * <br>            -> a real newline (Telegram would print the tag)
      * trailing "  "   -> markdown's hard break; just dangling whitespace here
      * "<url>..."      -> the spec's ellipsis copied onto the end of the link
      * em/en dashes    -> hyphen (the channel writes hyphens)
    """
    s = _BR_RE.sub("\n", s)
    s = _URL_TRAILING_DOTS.sub(r"\1", s)
    s = "\n".join(line.rstrip() for line in s.splitlines())
    return s.replace("—", "-").replace("–", "-")


def _extract_tag(raw: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", raw or "", re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def assemble_post(raw: str, link: str | None, footer: str | None = None,
                  layout: dict | None = None) -> str | None:
    """Arrange the model's tag sections per `layout` (default: the channel's separate-
    blocks look), swap the `<link/>` token for `link`, append `footer`. Different layouts
    give posts different shapes so a feed of them doesn't read as one template. Returns
    None if no sections were found so the caller can fall back to the template path."""
    tags = {k: _extract_tag(raw, k) for k in _TAG_ORDER}
    if not any(tags.values()):
        return None
    text = _LINK_TOKEN_RE.sub(lambda _m: link or "", render_layout(tags, layout))
    if footer and footer.strip():
        text += f"\n\n{footer.strip()}"
    return _clean(text.strip())


def assemble_loot(raw: str, links: list[str], cta: str | None = None,
                  footer: str | None = None) -> str | None:
    """Build the loot post from the model's <theme>/<items>/<closing> tags: swap each
    <LINK_n> for links[n-1], keep the theme, item block and closing line spaced, then
    append the CTA + share footer. <closing> is optional (older/degraded model output
    just omits the summary line). Returns None if theme/items are missing so the caller
    can fall back to the template."""
    theme = _extract_tag(raw, "theme")
    items = _extract_tag(raw, "items")
    closing = _extract_tag(raw, "closing")
    if not theme or not items:
        return None

    def _swap(m):
        i = int(m.group(1)) - 1
        return links[i] if 0 <= i < len(links) else ""

    theme = _LOOT_LINK_RE.sub(_swap, theme).strip()
    items = _LOOT_LINK_RE.sub(_swap, items).strip()
    text = f"{theme}\n\n{items}"
    if closing:
        text += f"\n\n{_LOOT_LINK_RE.sub(_swap, closing).strip()}"
    if cta and cta.strip():
        text += f"\n\n{cta.strip()}"
    if footer and footer.strip():
        text += f"\n{footer.strip()}"
    return _clean(text.strip())


class Copywriter:
    def __init__(self) -> None:
        self.ai = AIClient()

    def write_for_loot(self, items: list[dict], slot: dict | None, templates: dict | None,
                       style: dict, cta: str | None = None, footer: str | None = None,
                       price_cap: float | None = None, variant: int = 0) -> str:
        """Write a multi-category loot post. ``items`` is [{label, link}, ...] with links
        already finalized; the model writes <LINK_n> tokens we swap for them. `variant`
        rotates the banner FLAVOUR so loot boards vary in voice. Raises on unparseable
        output so the caller falls back to the deterministic template."""
        slot = slot or {}
        links = [it["link"] for it in items]
        numbered = "\n".join(f"{i + 1}. {it['label']} -> <LINK_{i + 1}>"
                             for i, it in enumerate(items))
        parts = [f"ITEMS (use each <LINK_n> exactly once):\n{numbered}"]
        if price_cap:
            parts.append(f"PRICE_CAP: {int(price_cap)}")
        exemplar = _exemplar("collection", templates)
        if exemplar:
            parts.append(f"FORMAT_REFERENCE (imitate the shape/tone):\n{exemplar}")
        ctx = {k: slot.get(k) for k in ("theme", "merchant", "why") if slot.get(k)}
        if ctx:
            parts.append(f"PLAN_CONTEXT:\n{to_json(ctx)}")
        parts.append(f"CHANNEL_STYLE:\n{to_json(style)}")
        parts.append(pick_loot_flavor(variant))
        raw = self.ai.complete("\n\n".join(parts), system_extra=_LOOT_INSTRUCTIONS,
                               max_tokens=600, effort="low", trace_call="copywriter_loot")
        text = assemble_loot(raw, links, cta, footer)
        if text is None:
            raise ValueError("loot copywriter output missing <theme>/<items> tags")
        return text

    def write_for_item(self, deal: EnrichedDeal, slot: dict | None,
                       templates: dict | None, style: dict, link: str | None = None,
                       footer: str | None = None, variant: int = 0) -> str:
        """Fill-time: write one deal post. `link` is the finalized tracked URL, `footer`
        the learned share line. `variant` selects a rotating post STYLE (tone + layout) so
        consecutive posts don't look alike. Raises on unparseable output -> caller falls back."""
        st = pick_style(variant)
        user = _build_prompt(_product_from_deal(deal), slot,
                             _exemplar((slot or {}).get("type"), templates), style)
        user = f"{user}\n\n{st.tone}"
        raw = self.ai.complete(user, system_extra=_INSTRUCTIONS, max_tokens=600, effort="low",
                               trace_call="copywriter_deal")
        text = assemble_post(raw, link, footer, layout=st.layout)
        if text is None:
            raise ValueError("copywriter output missing expected <hook>/<cta> tags")
        return text

    def write_for_deal(self, deal_id: str) -> str:
        with session_scope() as s:
            deal = s.scalar(select(EnrichedDeal).where(EnrichedDeal.deal_id == deal_id))
            if deal is None:
                return f"No enriched deal '{deal_id}'. Run `tgagent enrich-deals` first."
            link = deal.clean_url or deal.url
            user = _build_prompt(_product_from_deal(deal), None, "", channel_style(s))
        raw = self.ai.complete(user, system_extra=_INSTRUCTIONS, max_tokens=600, effort="low")
        return assemble_post(raw, link) or raw


def _selfcheck() -> None:
    tpl = {"single_price": "{price} ({discount}% off)", "single_loot_badge": "🔥 Loot",
           "loot_theme_default": "{category} Loot Deals", "loot_item": "{title} - {link}"}
    assert "🔥 Loot" in _exemplar("single", tpl) and "Loot Deals" not in _exemplar("single", tpl)
    assert "Loot Deals" in _exemplar("collection", tpl) and "🔥 Loot" not in _exemplar("collection", tpl)
    assert _exemplar("single", {}) == "" and _exemplar("single", None) == ""

    stub = {"title": "Widget", "link": _LINK_TOKEN}
    p = _build_prompt(stub, {"type": "single", "why": "peak hour"}, _exemplar("single", tpl), {})
    assert "peak hour" in p and "FORMAT_REFERENCE" in p and "<link/>" in p

    # discount and price are separate blocks, in tag order, bold passed through intact
    raw = ("<hook>🚨 THIS WON'T LAST!</hook>\n<name>Intex **Soundbar**</name>\n"
           "<discount>**91% OFF**</discount>\n<price>Now only **₹873**</price>\n"
           "<cta>👉 Grab it now: <link/></cta>")
    out = assemble_post(raw, "https://grbn.in/LD6G78", "🔁 Share • @GrabOnIndiaOfficial")
    assert ("THIS WON'T LAST!\n\nIntex **Soundbar**\n\n**91% OFF**\n\nNow only **₹873**"
            in out), out
    assert "https://grbn.in/LD6G78" in out and "<link/>" not in out
    assert out.strip().endswith("🔁 Share • @GrabOnIndiaOfficial")
    # an omitted optional tag must not leave a blank gap behind
    assert "\n\n\n" not in assemble_post(
        "<hook>Hi</hook>\n<name>Thing</name>\n<cta>👉 <link/></cta>", "https://grbn.in/X")
    assert assemble_post("prose, no tags", "https://grbn.in/X") is None

    lraw = ("<theme>Mega Fashion Loot 🔥\nUnder ₹500</theme>\n"
            "<items>\nMen T-Shirts - <LINK_1>\nJeans - <LINK_2>\n</items>\n"
            "<closing>Best Deals on Fashion & Essentials 🛒</closing>")
    lout = assemble_loot(lraw, ["https://grbn.in/A", "https://grbn.in/B"],
                         "Shop Now 👆", "🔁 Share • @GrabOnIndiaOfficial")
    assert "Mega Fashion Loot 🔥\nUnder ₹500\n\nMen T-Shirts - https://grbn.in/A" in lout
    assert "Jeans - https://grbn.in/B" in lout and "<LINK_" not in lout
    assert "https://grbn.in/B\n\nBest Deals on Fashion & Essentials 🛒\n\nShop Now 👆" in lout
    assert lout.strip().endswith("Shop Now 👆\n🔁 Share • @GrabOnIndiaOfficial")
    # <closing> is optional — no stray blank line when the model omits it
    lout2 = assemble_loot("<theme>T</theme>\n<items>A - <LINK_1></items>",
                          ["https://grbn.in/A"], "Shop Now 👆")
    assert lout2 == "T\n\nA - https://grbn.in/A\n\nShop Now 👆", repr(lout2)
    assert assemble_loot("no tags here", ["x"]) is None

    # gpt-4o-mini really emits <br> inside <theme> instead of a newline; Telegram would
    # print it literally. Also covers the em-dash strip in the same pass.
    br = assemble_loot("<theme>Fashion Steals!<br>Under ₹500</theme>\n"
                       "<items>Tops - <LINK_1></items>", ["https://grbn.in/A"])
    assert br.startswith("Fashion Steals!\nUnder ₹500"), repr(br)
    assert "<br" not in br.lower()
    for variant in ("<br>", "<br/>", "<BR />"):
        out = assemble_loot(f"<theme>A{variant}B</theme>\n<items>x - <LINK_1></items>", ["u"])
        assert out.startswith("A\nB"), (variant, repr(out))
    assert "—" not in assemble_post(
        "<hook>A — B</hook>\n<cta><link/></cta>", "https://grbn.in/X")
    # markdown hard-break: trailing spaces the model leaves on a line
    ws = assemble_loot("<theme>Loot 🌟  \nUnder ₹500  </theme>\n<items>x - <LINK_1>  </items>",
                       ["https://grbn.in/A"])
    assert not any(l != l.rstrip() for l in ws.splitlines()), repr(ws)

    # the spec's "..." copied onto the end of the link (observed from gpt-4o-mini)
    dots = assemble_post("<hook>Hi</hook>\n<cta>👉 <link/>...</cta>", "https://grbn.in/jkwiCP")
    assert dots.endswith("👉 https://grbn.in/jkwiCP"), repr(dots)
    mid = assemble_post("<hook>Hi</hook>\n<cta>👉 <link/>... grab it</cta>", "https://grbn.in/aB")
    assert "https://grbn.in/aB grab it" in mid, repr(mid)
    # a legitimate ellipsis NOT on a url must survive
    keep = assemble_post("<hook>Wait for it...</hook>\n<cta>👉 <link/></cta>", "https://grbn.in/X")
    assert "Wait for it..." in keep, repr(keep)
    print("copywriter selfcheck ok")


if __name__ == "__main__":
    _selfcheck()
