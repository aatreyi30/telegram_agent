"""Agentic Growth Coach.

Answers operator questions ("why am I not growing?", "what should I post today?",
"am I overusing Amazon?") by letting Claude call read-only tools over our engines
and reasoning strictly over what they return. This is the agentic surface: Claude
decides which engine outputs it needs, fetches them, and answers — grounded, with
no invented facts.
"""

from __future__ import annotations

from src.ai import context as ctx
from src.ai.client import AIClient
from src.ai.prompts import COACH_SYSTEM as _COACH_SYSTEM
from src.db.session import session_scope

# Read-only tools over the deterministic engines.
_TOOLS = [
    {"name": "get_channel", "description": "Channel overview: title, username, subscriber count.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_reasoning", "description": "What changed recently and WHY (period-over-period, data-backed).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_growth", "description": "Growth strategy blueprint + ranked recommendations.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_learnings", "description": "Post-type performance, channel style, and learned insights.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_merchant_intel", "description": "Merchant profiles (engagement/price) and opportunities.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_competitor_intel", "description": "Competitor profiles and similarity to us.",
     "input_schema": {"type": "object", "properties": {}}},
]


def _tool_runner(name: str, _input: dict) -> str:
    with session_scope() as s:
        if name == "get_channel":
            return ctx.to_json(ctx.channel_overview(s))
        if name == "get_reasoning":
            return ctx.to_json(ctx.reasoning_insights(s))
        if name == "get_growth":
            return ctx.to_json({"blueprint": ctx.growth_blueprint(s),
                                "recommendations": ctx.growth_recommendations(s)})
        if name == "get_learnings":
            return ctx.to_json({"post_type_performance": ctx.post_type_performance(s),
                                "style": ctx.channel_style(s),
                                "learnings": ctx.learnings(s)})
        if name == "get_merchant_intel":
            return ctx.to_json({"profiles": ctx.merchant_profiles(s),
                                "opportunities": ctx.merchant_opportunities(s)})
        if name == "get_competitor_intel":
            return ctx.to_json({"profiles": ctx.competitor_profiles(s)})
    return f"Unknown tool: {name}"


class GrowthCoach:
    def __init__(self) -> None:
        self.ai = AIClient()

    def ask(self, question: str) -> str:
        return self.ai.agentic(question, _TOOLS, _tool_runner,
                               system_extra=_COACH_SYSTEM, max_tokens=2000)
