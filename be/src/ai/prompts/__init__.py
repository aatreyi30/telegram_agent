"""Centralized LLM prompt strings for the `src.ai` package.

Every prompt constant/template used to build a request to the AI client lives
here, one module per consumer, so prompt text can be found, reviewed, and
changed in one place. Modules in this package are plain string constants (and
small pure string-building helpers) with NO imports from `src.ai.client` or
any other `src.ai.*` module — the dependency only ever runs the other way
(consumers import from `src.ai.prompts`), to avoid circular imports.
"""

from __future__ import annotations

from src.ai.prompts.briefing import DAILY_INSTRUCTIONS, WEEKLY_INSTRUCTIONS
from src.ai.prompts.coach import COACH_SYSTEM
from src.ai.prompts.copywriter import COPYWRITER_INSTRUCTIONS
from src.ai.prompts.discovery import VERIFY_CANDIDATE_SYSTEM, verify_candidate_input
from src.ai.prompts.grounding import GROUNDING_SYSTEM
from src.ai.prompts.insight_writer import NARRATE_SYSTEM
from src.ai.prompts.planner import PLAN_INSTRUCTIONS

__all__ = [
    "GROUNDING_SYSTEM",
    "PLAN_INSTRUCTIONS",
    "NARRATE_SYSTEM",
    "COACH_SYSTEM",
    "DAILY_INSTRUCTIONS",
    "WEEKLY_INSTRUCTIONS",
    "COPYWRITER_INSTRUCTIONS",
    "VERIFY_CANDIDATE_SYSTEM",
    "verify_candidate_input",
]
