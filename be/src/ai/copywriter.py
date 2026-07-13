"""AI post copywriter.

Writes a Telegram-native deal post from a real product, reproducing the channel's
own winning post format (the operator's saved deal/loot template) with the product's
real facts. It never invents a price, discount, feature, or link.

Two entry points:
  * ``write_for_item`` — fill-time path: caller already holds the freshly-scraped
    EnrichedDeal + the plan slot it fills + the org's post templates. Picks the
    deal or loot template by slot type and hands it to the model as the exemplar.
  * ``write_for_deal`` — CLI path: looks a deal up by id, no plan/template context.
"""

from __future__ import annotations

from sqlalchemy import select

from src.ai.client import AIClient
from src.ai.context import channel_style, to_json
from src.ai.prompts import COPYWRITER_INSTRUCTIONS as _INSTRUCTIONS
from src.db.models_generation import EnrichedDeal
from src.db.session import session_scope

# Which saved post_templates keys are the "winning format" exemplar per post type.
# Deal/single posts announce one product; loot/collection posts use the list format.
_DEAL_KEYS = ("single_loot_badge", "single_price", "single_coupon_line")
_LOOT_KEYS = ("collection_theme_default", "collection_item", "collection_footer")


def _product_from_deal(deal: EnrichedDeal) -> dict:
    product = {
        "title": deal.title, "merchant": deal.merchant_key,
        "current_price": deal.current_price, "mrp": deal.original_price,
        "discount_percent": deal.discount_percent,
        "is_loot_deal": deal.is_loot_deal, "coupon": None,
        "link": deal.clean_url or deal.url, "category": deal.category,
    }
    for t in (deal.tags or []):
        if isinstance(t, str) and t.startswith("coupon:"):
            product["coupon"] = t.split(":", 1)[1]
    return product


def _exemplar(slot_type: str | None, templates: dict | None) -> str:
    """The channel's winning post format for this slot type, as a placeholder
    blueprint. ``slot_type`` 'collection'/'loot' -> loot keys, else deal keys.
    Empty when no templates are configured (model falls back to channel style)."""
    templates = templates or {}
    loot = (slot_type or "").lower() in ("collection", "loot", "category_collection")
    keys = _LOOT_KEYS if loot else _DEAL_KEYS
    lines = [str(templates[k]) for k in keys if templates.get(k)]
    return "\n".join(lines)


def _build_prompt(product: dict, slot: dict | None, exemplar: str, style: dict) -> str:
    slot = slot or {}
    plan_context = {k: slot.get(k) for k in ("theme", "merchant", "type", "why") if slot.get(k)}
    parts = [f"PRODUCT:\n{to_json(product)}"]
    if exemplar:
        parts.append(f"TEMPLATE (winning format for this post type):\n{exemplar}")
    if plan_context:
        parts.append(f"PLAN_CONTEXT:\n{to_json(plan_context)}")
    parts.append(f"CHANNEL_STYLE:\n{to_json(style)}")
    return "\n\n".join(parts)


class Copywriter:
    def __init__(self) -> None:
        self.ai = AIClient()

    def write_for_item(self, deal: EnrichedDeal, slot: dict | None,
                       templates: dict | None, style: dict) -> str:
        """Fill-time: write the post for one scraped+enriched deal, styled by the
        slot's post-type template. Caller owns the session/objects (no DB lookup)."""
        user = _build_prompt(_product_from_deal(deal), slot,
                             _exemplar((slot or {}).get("type"), templates), style)
        return self.ai.complete(user, system_extra=_INSTRUCTIONS, max_tokens=600, effort="low")

    def write_for_deal(self, deal_id: str) -> str:
        with session_scope() as s:
            deal = s.scalar(select(EnrichedDeal).where(EnrichedDeal.deal_id == deal_id))
            if deal is None:
                return f"No enriched deal '{deal_id}'. Run `tgagent enrich-deals` / `generate-live` first."
            user = _build_prompt(_product_from_deal(deal), None, "", channel_style(s))
        return self.ai.complete(user, system_extra=_INSTRUCTIONS, max_tokens=600, effort="low")


def _selfcheck() -> None:
    tpl = {"single_price": "{price} ({discount}% off)", "single_loot_badge": "🔥 Loot",
           "collection_theme_default": "TOP 10 — {date}", "collection_item": "{n} {title}"}
    assert "🔥 Loot" in _exemplar("single", tpl) and "TOP 10" not in _exemplar("single", tpl)
    assert "TOP 10" in _exemplar("collection", tpl) and "🔥 Loot" not in _exemplar("collection", tpl)
    assert _exemplar("single", {}) == "" and _exemplar("single", None) == ""
    p = _build_prompt({"title": "Widget", "link": "u"}, {"type": "single", "why": "peak hour"},
                      _exemplar("single", tpl), {"emoji": []})
    assert "Widget" in p and "peak hour" in p and "🔥 Loot" in p and "TEMPLATE" in p
    print("copywriter selfcheck ok")


if __name__ == "__main__":
    _selfcheck()
