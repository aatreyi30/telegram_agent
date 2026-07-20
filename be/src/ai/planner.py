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
from src.ai.prompts import WEEK_PLAN_INSTRUCTIONS as _WEEK_PLAN_INSTRUCTIONS

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


def _current_week_plan(s: Session) -> dict | None:
    """The current week's WEEKLY CampaignPlan blueprint (most recent row for this
    campaign version — the AI weekly plan when one exists, else the deterministic one)."""
    from sqlalchemy import select
    from src.db.models_campaign import CAMPAIGN_VERSION, CampaignPlan, PlanType

    wk = s.scalar(
        select(CampaignPlan)
        .where(CampaignPlan.campaign_version == CAMPAIGN_VERSION,
               CampaignPlan.plan_type == PlanType.WEEKLY)
        .order_by(CampaignPlan.generated_at.desc())
    )
    return (wk.blueprint or {}) if wk else None


def _week_theme_for(day, blueprint: dict | None) -> dict | None:
    """The weekly blueprint's daily_themes entry for ``day``'s weekday, if any.
    daily_themes stores abbreviated weekdays (campaign.py's WEEKDAYS list)."""
    themes = (blueprint or {}).get("daily_themes") or []
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
    # Cold-start floor: an empty recent window (e.g. a fresh channel whose only posts
    # are TODAY, which the yesterday-ending trajectory excludes) falls back to the
    # lifetime average, so the AI doesn't ground the plan on a phantom 0 cadence and
    # emit zero slots. Truly zero only when there is no posting history at all.
    recent_cadence = traj["recent_cadence"] or round(traj["lifetime_baseline"] or 0)
    recommended_posts = inputs.get("recommended_posts", recent_cadence)
    # Available deals from the live feed (limit = 3x today's slots) — the pool the
    # plan themes slots around. No scoring; ordered by discount.
    available_deals = ctx.available_deals(s, limit=max(3 * (recommended_posts or 0), 9))
    week_bp = _current_week_plan(s)
    week_direction = ({k: week_bp.get(k) for k in ("direction", "loot_deal_ratio", "merchant_priorities")}
                      if week_bp else None)
    # The real vocabulary the live deal feed uses — the plan's slot `theme`/`merchant`
    # must come from these so the just-in-time filler can actually match an item to
    # each slot (otherwise it silently falls back to any fresh deal).
    available_categories = sorted({d["category"] for d in available_deals if d.get("category")})
    available_merchants = sorted({d["merchant_key"] for d in available_deals if d.get("merchant_key")})
    # Per-day follower deltas lined up with the trajectory days, so the planner sees the
    # follower curve next to the posting curve (not just yesterday's net).
    from datetime import date as _date
    from src.services.analytics.daily_report import _owned_channel
    owned_ch = _owned_channel(s)
    traj_days = traj["days"]
    fdeltas = (ctx.follower_deltas_by_day(
        s, owned_ch.id, _date.fromisoformat(traj_days[0]["date"]),
        _date.fromisoformat(traj_days[-1]["date"]))
        if traj_days and owned_ch else {})
    follower_trajectory = [{"date": d["date"], **(fdeltas.get(d["date"])
                            or {"joined": None, "left": None, "net": None})}
                           for d in traj_days]
    return {
        "today": day.isoformat(),
        "day_of_week": day.strftime("%A"),
        "this_week_theme": _week_theme_for(day, week_bp),
        "this_week_direction": week_direction,
        "available_categories": available_categories,
        "available_merchants": available_merchants,
        "yesterday": yesterday,
        "yesterday_digest": yesterday_plan.ai_digest if yesterday_plan else None,
        "trajectory": traj["days"],
        "recent_cadence": recent_cadence,
        "lifetime_baseline": traj["lifetime_baseline"],
        "recommended_posts": recommended_posts,
        "posting_windows": inputs.get("posting_windows", []),
        "deal_type_allocation": inputs.get("deal_type_allocation", []),
        "merchant_mix": inputs.get("merchant_allocation", []),
        "post_type_performance": ctx.post_type_performance(s),
        "channel_style": ctx.channel_style(s),
        "follower_trajectory": follower_trajectory,
        "style_follower_correlation": ctx.style_follower_correlation(s, days=14, end_day=prev),
        "competitor_benchmark": ctx.competitor_benchmark(s),
        "upcoming_event": inputs.get("upcoming_event"),
        "retro": ctx.latest_retro(s),
        "available_deals": available_deals,
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
    # Each available deal is its own top-level fact item (not nested under a
    # wrapper key), same one-level-of-nesting reasoning as the retro above, so a
    # cited price/discount value is verifiable.
    facts.extend(plan_ctx.get("available_deals") or [])
    # The prompt SHOWS the AI these grounded inputs and instructs it to cite them
    # (merchant share/avg-views, per-window averages, deal-type + post-type stats).
    # They must be in the factcheck pool too — otherwise legitimately-cited numbers
    # like "amazon share 0.316, 48.5 views/day" are flagged as hallucinations and
    # the whole plan is marked untrusted (so jit_fill refuses to fill it). Each is a
    # list of dicts; check_cited_numbers flattens one level, exposing their numeric
    # fields. This corrects an omission in the guard — it does not weaken it.
    for _key in ("merchant_mix", "posting_windows", "deal_type_allocation",
                 "post_type_performance", "follower_trajectory"):
        facts.extend(plan_ctx.get(_key) or [])
    # New grounded signals (style + follower correlation + competitor benchmark): their
    # numbers must be in the fact-check pool too, same reasoning as the block above.
    # Each is a flat dict or a list of flat dicts, so check_cited_numbers exposes them.
    if plan_ctx.get("channel_style"):
        facts.append(plan_ctx["channel_style"])
    sfc = plan_ctx.get("style_follower_correlation") or {}
    facts.extend(sfc.get("days") or [])
    facts.extend(sfc.get("comparisons") or [])
    cb = plan_ctx.get("competitor_benchmark") or {}
    if cb.get("available"):
        facts.append(cb.get("competitors_avg") or {})
        facts.append(cb.get("ours") or {})
        facts.extend(cb.get("merchant_share_vs_competitors") or [])
    ai = AIClient()
    recon_note = ""
    if yesterday_plan is not None and yesterday_plan.reconciliation:
        recon_note = ("\n\nYESTERDAY'S RECONCILIATION (adherence is fact; attribution is "
                      "correlational, not causal):\n" + to_json(yesterday_plan.reconciliation))
    directive_note = ""
    if directive:
        avail = plan_ctx.get("available_merchants") or []
        directive_note = (
            "\n\nOPERATOR DIRECTIVE (highest priority — honor it, or state PLAINLY in the "
            "narrative why it can't be honored). CRITICAL: the ONLY merchants with deals in "
            f"today's feed are {avail} — a slot's merchant MUST be one of these. If the "
            "directive asks to diversify merchants or use a merchant not in that list, you "
            "CANNOT — say so explicitly and name what IS available (e.g. \"today's feed only "
            "has ajio deals, so every slot stays ajio; I can't add other merchants until the "
            "feed carries them\"). Never silently keep the same merchants without explaining "
            "this constraint.\n" + directive
        )
    try:
        user = f"DATA:\n{to_json(plan_ctx)}{recon_note}{directive_note}"
        raw = ai.complete(user, system_extra=_PLAN_INSTRUCTIONS, max_tokens=3200,
                          trace_call="day_plan")
    except AIUnavailable as e:
        return {"available": False, "reason": str(e), "plan": None, "digest": "", "facts": facts}
    digest, plan_text = _split_digest_and_plan(raw)
    try:
        plan = parse_plan(plan_text)
    except ValueError:
        return {"available": False, "reason": "unparseable plan", "plan": None,
                "digest": digest, "facts": facts}
    return {"available": True, "digest": digest, "plan": plan, "facts": facts}


def _parse_week_plan(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("no JSON object found in model output")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"weekly plan JSON invalid: {e}") from e
    data.setdefault("daily_themes", [])
    data.setdefault("cited_numbers", [])
    if not isinstance(data["daily_themes"], list):
        raise ValueError("daily_themes must be a list")
    return data


def generate_week_plan(s: Session, week_start=None, directive: str | None = None) -> dict:
    """Grounded AI WEEKLY plan. Analyses last week's evidence — which post type (loot vs
    single) and which merchants drew traction — and sets THIS week's direction: the
    loot:deal ratio to aim for, merchant priorities, and a per-day theme_focus. The
    digest doubles as the operator's weekly retro (win/concern/what-to-change). The
    daily planner reads this week's plan (``this_week_theme``) and aligns its slots to
    it. ``directive`` is an optional Steer & Regenerate operator instruction injected as
    a highest-priority block. Returns the raw digest + parsed plan + grounding facts."""
    from datetime import timedelta
    from src.ai.context import full_briefing_context
    from src.services.analytics.periods import ist_today

    if week_start is None:
        today = ist_today()
        week_start = today - timedelta(days=today.weekday())  # IST Monday

    facts_ctx = full_briefing_context(s, weekly=True)
    # Flatten the new grounded signals into the fact-check pool as their own items so
    # cited style/follower/competitor numbers verify (nested lists inside facts_ctx are
    # otherwise invisible to check_cited_numbers, which flattens only one level).
    facts = [facts_ctx]
    sfc = facts_ctx.get("style_follower_correlation") or {}
    facts.extend(sfc.get("days") or [])
    facts.extend(sfc.get("comparisons") or [])
    cb = facts_ctx.get("competitor_benchmark") or {}
    if cb.get("available"):
        facts.append(cb.get("competitors_avg") or {})
        facts.append(cb.get("ours") or {})
        facts.extend(cb.get("merchant_share_vs_competitors") or [])
    ai = AIClient()
    directive_note = ""
    if directive:
        directive_note = (
            "\n\nOPERATOR DIRECTIVE (highest priority — honor it in the direction/digest, "
            "or state plainly why the DATA can't support it; never invent a fact):\n" + directive
        )
    try:
        user = f"WEEK_START: {week_start.isoformat()}\n\nDATA:\n{to_json(facts_ctx)}{directive_note}"
        raw = ai.complete(user, system_extra=_WEEK_PLAN_INSTRUCTIONS, max_tokens=2000,
                          trace_call="week_plan")
    except AIUnavailable as e:
        return {"available": False, "reason": str(e), "plan": None, "digest": "",
                "facts": facts}
    digest, plan_text = _split_digest_and_plan(raw)
    try:
        plan = _parse_week_plan(plan_text)
    except ValueError:
        return {"available": False, "reason": "unparseable weekly plan", "plan": None,
                "digest": digest, "facts": facts}
    plan.setdefault("week_start", week_start.isoformat())
    return {"available": True, "digest": digest, "plan": plan, "facts": facts}
