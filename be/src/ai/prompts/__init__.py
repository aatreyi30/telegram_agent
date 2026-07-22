"""Centralized LLM prompt strings for the `src.ai` package.

Every prompt used to build a request to the AI client lives here — ONE file per
prompt, the file name saying exactly what that prompt produces, so any prompt can
be found, reviewed, and changed in one place:

    grounding.py          GROUNDING_SYSTEM        anti-hallucination contract on EVERY call
    daily_plan.py         DAILY_PLAN_SYSTEM       builds the day's slot schedule
    weekly_plan.py        WEEKLY_PLAN_SYSTEM      sets the week's direction the daily plans follow
    single_deal_post.py   SINGLE_DEAL_POST_SYSTEM writes ONE single-product deal post
    loot_post.py          LOOT_POST_SYSTEM        writes ONE loot board (multi-category)
    insight_line.py       INSIGHT_LINE_SYSTEM     one-sentence "why it matters" on a dashboard card
    competitor_check.py   COMPETITOR_CHECK_SYSTEM decides if a channel is a brand's real competitor
    coach.py              COACH_SYSTEM            growth-coach chat (CLI only)

Modules here are plain string constants (and small pure string-building helpers)
with NO imports from `src.ai.client` or any other `src.ai.*` module — the
dependency only ever runs the other way (consumers import from `src.ai.prompts`),
to avoid circular imports.
"""

from __future__ import annotations

from src.ai.prompts.coach import COACH_SYSTEM
from src.ai.prompts.competitor_check import COMPETITOR_CHECK_SYSTEM, competitor_check_input
from src.ai.prompts.daily_plan import DAILY_PLAN_SYSTEM
from src.ai.prompts.grounding import GROUNDING_SYSTEM
from src.ai.prompts.insight_line import INSIGHT_LINE_SYSTEM
from src.ai.prompts.loot_post import LOOT_POST_SYSTEM
from src.ai.prompts.single_deal_post import SINGLE_DEAL_POST_SYSTEM
from src.ai.prompts.weekly_plan import WEEKLY_PLAN_SYSTEM

__all__ = [
    "GROUNDING_SYSTEM",
    "DAILY_PLAN_SYSTEM",
    "WEEKLY_PLAN_SYSTEM",
    "SINGLE_DEAL_POST_SYSTEM",
    "LOOT_POST_SYSTEM",
    "INSIGHT_LINE_SYSTEM",
    "COMPETITOR_CHECK_SYSTEM",
    "competitor_check_input",
    "COACH_SYSTEM",
]
