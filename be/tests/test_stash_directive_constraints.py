"""_stash_directive_constraints must derive HARD constraints (merchant/category pins)
from the operator's RAW steer text only — never from prompt-only decoration appended
to `directive` for the AI's context (e.g. an "ALREADY POSTED TODAY: ... amazon ..."
note listing real merchant names purely so the model doesn't repeat itself).

Regression for a real live bug: regenerating a day's plan with an EMPTY steer box
still built a non-empty `directive` string (the "already posted" note), which the
regex fallback then misread as "operator wants amazon only" — permanently re-pinning
every future regeneration to whatever merchant history happened to contain, even
though nothing was actually steered."""
from __future__ import annotations

from src.ai.planner import _stash_directive_constraints


def _plan_ctx():
    return {"available_merchants": ["amazon", "flipkart", "myntra", "ajio"],
            "available_categories": ["electronics-and-gadgets", "general"]}


def test_decorated_directive_with_no_real_steer_stashes_nothing():
    # This is exactly the "ALREADY POSTED TODAY" note regenerate_daily builds when
    # the steer box was empty — it repeats "amazon" many times, purely as context.
    decorated = ("\n\nALREADY POSTED TODAY — 3 posts are already live and CANNOT "
                 "change: 06:01 loot amazon/general; 06:08 single amazon/general; "
                 "06:46 single amazon/electronics-and-gadgets.\nPlan ONLY the "
                 "remaining slots.")
    plan = {}
    _stash_directive_constraints(plan, decorated, None, _plan_ctx(),
                                 constraint_directive="")
    assert "_directive_constraints" not in plan


def test_decorated_directive_with_a_real_steer_still_stashes_it():
    decorated = ("only amazon today" + "\n\nALREADY POSTED TODAY — 1 posts are "
                 "already live and CANNOT change: 06:01 loot flipkart/general.")
    plan = {}
    _stash_directive_constraints(plan, decorated, None, _plan_ctx(),
                                 constraint_directive="only amazon today")
    assert plan["_directive_constraints"]["merchants"] == ["amazon"]


def test_no_constraint_directive_falls_back_to_directive_unchanged():
    # Backward compatibility: callers that never decorate `directive` (pass the raw
    # operator text straight through, omitting constraint_directive) keep working
    # exactly as before.
    plan = {}
    _stash_directive_constraints(plan, "only amazon today", None, _plan_ctx())
    assert plan["_directive_constraints"]["merchants"] == ["amazon"]