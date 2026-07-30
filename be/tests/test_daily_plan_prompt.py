"""Regression guard: the daily plan prompt must explicitly tell the model to use
RECOMMENDED_POSTS (the deterministic target — the channel's own cadence read PLUS
any active event ramp or weekly-plan alignment) exactly, not re-derive its own
number from RECENT_CADENCE. Found live: a weekly plan aligned/ramped to 105/day
(a real Croma Independence Day Sale ramp), but the daily plan's AI independently
decided "2 posts" from a quiet recent-activity read, since the prompt only ever
told it to ground recommended_posts in RECENT_CADENCE/trajectory — RECOMMENDED_POSTS
wasn't even described as a DATA field, let alone something to comply with."""
from src.ai.prompts.daily_plan import DAILY_PLAN_SYSTEM


def test_prompt_describes_recommended_posts_as_a_data_field():
    assert "RECOMMENDED_POSTS" in DAILY_PLAN_SYSTEM


def test_prompt_requires_using_recommended_posts_exactly():
    assert "recommended_posts to RECOMMENDED_POSTS EXACTLY" in DAILY_PLAN_SYSTEM
    assert "do not re-derive a different number" in DAILY_PLAN_SYSTEM