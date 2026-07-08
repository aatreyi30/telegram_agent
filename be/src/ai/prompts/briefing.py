"""Daily/weekly briefing instructions, consumed by `src.ai.briefing.BriefingGenerator`."""

from __future__ import annotations

DAILY_INSTRUCTIONS = (
    "Write today's growth briefing for the channel operator, using ONLY the DATA below. "
    "Structure it as:\n"
    "1. One-line headline — did the channel improve or slip, and the single biggest reason.\n"
    "2. What changed & why — 2-4 plain bullets from 'what_changed_and_why'.\n"
    "3. Do today — the top 2-3 growth recommendations, each with the number that justifies it.\n"
    "4. Watch — the most important competitor signal or risk, if any.\n"
    "Keep it under ~200 words. If a section has no supporting data, omit it and say so briefly. "
    "'what_changed_and_why' and 'growth_recommendations' can stem from the same underlying "
    "learning — if a fact would appear in both section 2 and section 3, state it once (in "
    "whichever section fits best) and don't repeat the same explanation twice. "
    "Never introduce a fact that is not in the DATA."
)

WEEKLY_INSTRUCTIONS = (
    "Write this week's growth summary for the operator, using ONLY the DATA below. Cover: "
    "biggest win, biggest concern, what's working (top post types with their numbers), "
    "what to change next week (from the recommendations), and the key competitor note. "
    "If the same underlying fact would justify two sections, state it once and reference it "
    "briefly the second time rather than repeating the full explanation. "
    "Under ~300 words. Never introduce a fact not present in the DATA."
)
