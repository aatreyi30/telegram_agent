"""AI daily / weekly growth briefing.

Turns the verified engine outputs (reasoning, growth recs, competitor signals,
merchant opportunities) into the operator's plain-language morning briefing.
Grounded: the model only narrates the data bundle it is given.
"""

from __future__ import annotations

from src.ai.client import AIClient
from src.ai.context import full_briefing_context, to_json
from src.ai.prompts import DAILY_INSTRUCTIONS as _DAILY_INSTRUCTIONS
from src.ai.prompts import WEEKLY_INSTRUCTIONS as _WEEKLY_INSTRUCTIONS
from src.db.session import session_scope


class BriefingGenerator:
    def __init__(self) -> None:
        self.ai = AIClient()

    def generate(self, weekly: bool = False) -> str:
        with session_scope() as s:
            ctx = full_briefing_context(s, weekly=weekly)
        if not ctx["channel"].get("available"):
            return "No channel data yet — run collection and the intelligence engines first."
        instructions = _WEEKLY_INSTRUCTIONS if weekly else _DAILY_INSTRUCTIONS
        user = f"DATA:\n{to_json(ctx)}"
        return self.ai.complete(user, system_extra=instructions, max_tokens=1500, effort="medium")
