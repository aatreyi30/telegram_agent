"""AI analyst + planner. Reads DailyChannelReport rows, emits a grounded digest
+ structured day plan. AIClient has no JSON mode, so we prompt for JSON and
parse defensively; numbers are fact-checked downstream (ai/factcheck.py)."""
from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from src.ai.client import AIClient, AIUnavailable
from src.ai.context import planning_context, to_json
from src.ai.prompts import PLAN_INSTRUCTIONS as _PLAN_INSTRUCTIONS

PLAN_SCHEMA_KEYS = ("date", "recommended_posts", "cadence_why", "post_slots",
                    "emphasis", "watch", "cited_numbers")


def parse_plan(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("no JSON object found in model output")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"plan JSON invalid: {e}") from e
    data.setdefault("post_slots", [])
    data.setdefault("cited_numbers", [])
    data.setdefault("recommended_posts", None)
    data.setdefault("cadence_why", "")
    if not isinstance(data.get("post_slots"), list):
        raise ValueError("post_slots must be a list")
    return data


def _split_digest_and_plan(raw: str) -> tuple[str, str]:
    if "===PLAN===" in raw:
        digest, _, plan = raw.partition("===PLAN===")
        return digest.strip(), plan.strip()
    # fallback: digest is everything before the first '{'
    idx = raw.find("{")
    return (raw[:idx].strip() if idx > 0 else ""), raw[idx:] if idx >= 0 else raw


_UNSET = object()


def _yesterday_ai_plan(s: Session, prev):
    """The AI-generated DAILY CampaignPlan row for exactly ``prev``, if one exists."""
    from sqlalchemy import select
    from src.db.models_campaign import CampaignPlan, PlanType

    return s.scalar(
        select(CampaignPlan)
        .where(CampaignPlan.plan_type == PlanType.DAILY,
               CampaignPlan.target_date == prev,
               CampaignPlan.is_ai_generated == True)  # noqa: E712
        .order_by(CampaignPlan.generated_at.desc())
    )


def _current_week_theme(s: Session, day) -> dict | None:
    """The current week's CampaignPlan(WEEKLY) blueprint entry for ``day``'s weekday.
    Mirrors service.py::weekly_brief's lookup of "the current week's plan" (most
    recent WEEKLY row for this campaign version)."""
    from sqlalchemy import select
    from src.db.models_campaign import CAMPAIGN_VERSION, CampaignPlan, PlanType

    wk = s.scalar(
        select(CampaignPlan)
        .where(CampaignPlan.campaign_version == CAMPAIGN_VERSION,
               CampaignPlan.plan_type == PlanType.WEEKLY)
        .order_by(CampaignPlan.generated_at.desc())
    )
    themes = ((wk.blueprint or {}).get("daily_themes") if wk else None) or []
    # daily_themes stores abbreviated weekdays (campaign.py's WEEKDAYS list)
    target = day.strftime("%a").lower()
    return next((t for t in themes if (t.get("day") or "")[:3].lower() == target), None)


def build_plan_context(s: Session, day, inputs: dict | None = None,
                        yesterday_plan=_UNSET, directive: str | None = None) -> dict:
    """Assemble the grounded facts for planning ``day``: yesterday's results (report
    or live), the 14-day posting trajectory (ending yesterday), the recent cadence,
    the stale lifetime baseline, post-type performance, the day of week, this week's
    theme (if a weekly plan exists), and yesterday's AI digest (if it generated one).
    ``inputs`` carries the deterministic targets (recommended count, posting windows,
    deal-type allocation, merchant mix) the AI turns into a concrete slot schedule.
    Never bails on missing reports — falls back to live day-facts computed from
    posts. ``yesterday_plan`` lets callers that already fetched yesterday's
    CampaignPlan row (e.g. ``generate_day_plan``, for its reconciliation note) pass
    it in instead of this function querying it again. ``directive`` is the Steer &
    Regenerate operator directive (if any); it's surfaced here too (not just in the
    prompt's appended block) so callers/tests can inspect it alongside the rest of
    the grounding context."""
    from datetime import timedelta
    from src.ai import context as ctx

    prev = day - timedelta(days=1)
    yesterday = ctx.daily_report_or_live(s, prev)
    traj = ctx.posting_trajectory(s, days=14, end_day=prev)
    inputs = inputs or {}
    if yesterday_plan is _UNSET:
        yesterday_plan = _yesterday_ai_plan(s, prev)
    recommended_posts = inputs.get("recommended_posts", traj["recent_cadence"])
    # Phase 3.3 -- top-N audience-scored deals (limit = 3x today's slots), with
    # `components` included so the AI can cite/explain a specific deal's score.
    scored_deals = ctx.top_scored_deals(s, limit=max(3 * (recommended_posts or 0), 9))
    return {
        "today": day.isoformat(),
        "day_of_week": day.strftime("%A"),
        "this_week_theme": _current_week_theme(s, day),
        "yesterday": yesterday,
        "yesterday_digest": yesterday_plan.ai_digest if yesterday_plan else None,
        "trajectory": traj["days"],
        "recent_cadence": traj["recent_cadence"],
        "lifetime_baseline": traj["lifetime_baseline"],
        "recommended_posts": recommended_posts,
        "posting_windows": inputs.get("posting_windows", []),
        "deal_type_allocation": inputs.get("deal_type_allocation", []),
        "merchant_mix": inputs.get("merchant_allocation", []),
        "post_type_performance": ctx.post_type_performance(s),
        "upcoming_event": inputs.get("upcoming_event"),
        "retro": ctx.latest_retro(s),
        "scored_deals": scored_deals,
        "operator_directive": directive,
    }


def generate_day_plan(s: Session, day=None, inputs: dict | None = None,
                       directive: str | None = None) -> dict:
    """Grounded AI day plan for ``day`` (default: latest owned day). Returns the raw
    digest + parsed plan and the facts it was given (so callers can fact-check).
    ``inputs`` supplies the deterministic targets the AI expands into a slot schedule.
    ``directive`` is an optional Steer & Regenerate operator directive: free-text
    guidance injected into the prompt as a highest-priority block (mirroring the
    yesterday's-reconciliation note below) that the AI must honor or explicitly
    reject in the digest — it never bypasses the downstream fact-check, since the
    plan's cited numbers are still verified against ``facts`` regardless."""
    from datetime import timedelta

    from src.services.analytics.day import latest_owned_date

    if day is None:
        day = latest_owned_date(s)
    if day is None:
        return {"available": False, "reason": "no owned posts yet", "plan": None,
                "digest": "", "facts": []}

    prev = day - timedelta(days=1)
    try:
        yesterday_plan = _yesterday_ai_plan(s, prev)
    except Exception:
        yesterday_plan = None

    plan_ctx = build_plan_context(s, day, inputs, yesterday_plan=yesterday_plan, directive=directive)
    facts = [plan_ctx["yesterday"], *plan_ctx["trajectory"]]
    retro = plan_ctx.get("retro")
    if retro and retro.get("metrics"):
        # Appended as its OWN top-level item (not nested under a wrapper key) --
        # factcheck._numeric_values only flattens one level of dict nesting, so
        # the retro's numbers (metrics.prediction.*, metrics.plan_adherence.*, ...)
        # need to sit exactly one level below what's in `facts` to be verifiable.
        facts.append(retro["metrics"])
    # Phase 3.3 -- each scored deal is its own top-level fact item (not nested
    # under a wrapper key), same one-level-of-nesting reasoning as the retro
    # above, so a cited `score` or `components.*` value is verifiable.
    facts.extend(plan_ctx.get("scored_deals") or [])
    ai = AIClient()
    recon_note = ""
    if yesterday_plan is not None and yesterday_plan.reconciliation:
        recon_note = ("\n\nYESTERDAY'S RECONCILIATION (adherence is fact; attribution is "
                      "correlational, not causal):\n" + to_json(yesterday_plan.reconciliation))
    directive_note = ""
    if directive:
        directive_note = (
            "\n\nOPERATOR DIRECTIVE (highest priority — honor it, or explicitly state in "
            "the narrative why it can't be honored given the data):\n" + directive
        )
    try:
        user = f"DATA:\n{to_json(plan_ctx)}{recon_note}{directive_note}"
        raw = ai.complete(user, system_extra=_PLAN_INSTRUCTIONS, max_tokens=2400)
    except AIUnavailable as e:
        return {"available": False, "reason": str(e), "plan": None, "digest": "", "facts": facts}
    digest, plan_text = _split_digest_and_plan(raw)
    try:
        plan = parse_plan(plan_text)
    except ValueError:
        return {"available": False, "reason": "unparseable plan", "plan": None,
                "digest": digest, "facts": facts}
    return {"available": True, "digest": digest, "plan": plan, "facts": facts}
