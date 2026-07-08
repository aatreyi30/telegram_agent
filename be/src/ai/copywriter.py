"""AI post copywriter.

Writes a Telegram-native deal post from an enriched deal (or category collection),
using ONLY the product facts provided and the channel's learned style. It never
invents a price, discount, feature, or link — those come from the enriched deal.

This is the generative counterpart to the deterministic formatter: same grounding
(real fields, learned style), but Claude writes the human-facing copy.
"""

from __future__ import annotations

from sqlalchemy import select

from src.ai.client import AIClient
from src.ai.context import channel_style, to_json
from src.ai.prompts import COPYWRITER_INSTRUCTIONS as _INSTRUCTIONS
from src.db.models_generation import EnrichedDeal
from src.db.session import session_scope


class Copywriter:
    def __init__(self) -> None:
        self.ai = AIClient()

    def write_for_deal(self, deal_id: str) -> str:
        with session_scope() as s:
            deal = s.scalar(select(EnrichedDeal).where(EnrichedDeal.deal_id == deal_id))
            if deal is None:
                return f"No enriched deal '{deal_id}'. Run `tgagent enrich-deals` / `generate-live` first."
            product = {
                "title": deal.title, "merchant": deal.merchant_key,
                "current_price": deal.current_price, "mrp": deal.original_price,
                "discount_percent": deal.discount_percent,
                "is_loot_deal": deal.is_loot_deal, "coupon": None,
                "link": deal.clean_url or deal.url, "category": deal.category,
                "tags": deal.tags,
            }
            for t in (deal.tags or []):
                if isinstance(t, str) and t.startswith("coupon:"):
                    product["coupon"] = t.split(":", 1)[1]
            style = channel_style(s)
        user = (f"{_INSTRUCTIONS}\n\nPRODUCT:\n{to_json(product)}\n\n"
                f"CHANNEL STYLE:\n{to_json(style)}")
        return self.ai.complete(user, max_tokens=600, effort="low")
