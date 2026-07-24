"""AI analyst + planner. Reads DailyChannelReport rows, emits a grounded digest
+ structured day plan. AIClient has no JSON mode, so we prompt for JSON and
parse defensively; numbers are fact-checked downstream (ai/factcheck.py)."""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from src.ai.client import AIClient, AIUnavailable
from src.ai.context import planning_context, to_json
from src.ai.prompts import DAILY_PLAN_SYSTEM as _DAILY_PLAN_SYSTEM
from src.ai.prompts import WEEKLY_PLAN_SYSTEM as _WEEKLY_PLAN_SYSTEM
from src.logger import get_logger

logger = get_logger(__name__)

PLAN_SCHEMA_KEYS = ("date", "recommended_posts", "cadence_why", "post_slots",
                    "emphasis", "watch", "cited_numbers")

# G3/G6 shared defaults: a 60/40 single-lean split (single out-performs loot in the
# live stats today) with a hard 30% floor per type so neither ever drops to zero —
# see data_flow.md §2/§6. Used both as the deterministic fallback's split and to
# fill in a share the weekly AI left out (_parse_week_plan below).
_DEFAULT_LOOT_SHARE = 0.4
_MIN_TYPE_SHARE = 0.3

# ponytail: soft cap on any single merchant's share of a day's slots, enforced by
# _repair_merchant_diversity below. Tune here if the diversity floor needs to move.
_MAX_MERCHANT_SHARE = 0.4


def _repair_merchant_diversity(slots: list[dict], available_merchants: list[str] | None) -> None:
    """Enforce merchant rotation the prompt only asks for (whole windows come back
    one merchant otherwise). Keep the model's merchant unless it repeats the prior
    slot in the same window, isn't in today's feed, or exceeds ``_MAX_MERCHANT_SHARE``
    — reassigning the fewest slots possible. A reassigned slot's ``why`` was written
    for the OLD merchant, so overwrite it with a number-free rotation note (else the
    text contradicts the data). No-op with <2 available merchants (a feed constraint)."""
    merchants = [m for m in (available_merchants or []) if m]
    if len(merchants) < 2 or not slots:
        return
    windows: dict[str, list[dict]] = {}
    for sl in slots:
        windows.setdefault(sl.get("window_ist") or "", []).append(sl)
    cap = max(round(len(slots) * _MAX_MERCHANT_SHARE), 1)
    counts = {m: 0 for m in merchants}
    for win, win_slots in windows.items():
        prev = None
        for sl in win_slots:
            cur = sl.get("merchant")
            keep = (cur in counts and cur != prev and counts[cur] < cap)
            if keep:
                m = cur
            else:
                eligible = [x for x in merchants if counts[x] < cap] or merchants
                pick_from = [x for x in eligible if x != prev] or eligible
                m = min(pick_from, key=lambda x: counts[x])
                if m != cur:
                    sl["merchant"] = m
                    sl["why"] = (f"Assigned {m} to keep the {win or 'day'} window "
                                 "from concentrating on one store — auto-balanced for "
                                 "merchant diversity, so this slot rotates off the "
                                 "merchant the previous slot used.")
            counts[m] += 1
            prev = m


def _extract_json_object(text: str) -> str | None:
    """The first top-level {...} object in ``text``, found by counting brace
    depth (string-literal aware) rather than ``re.search(r"\\{.*\\}")``. The
    regex is greedy and DOTALL, so it spans from the FIRST '{' to the LAST '}'
    in the whole text — if the model appends any trailing content containing
    its own '}' (a stray aside, a second example, markdown), the regex swallows
    it too and json.loads fails with "Extra data". Scanning for the position
    where depth actually returns to 0 gets exactly the real object regardless
    of what follows it."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def parse_plan(raw: str, available_merchants: list[str] | None = None) -> dict:
    obj = _extract_json_object(raw)
    if obj is None:
        raise ValueError("no JSON object found in model output")
    try:
        # strict=False: the model occasionally embeds a raw control character
        # inside a string value (e.g. a stray byte in a "why" field) — valid
        # enough to mean, invalid per strict JSON's ban on unescaped control
        # chars in strings. That was rejecting a real, well-formed plan and
        # falling back to the generic deterministic one ~1 in 4-8 generations.
        data = json.loads(obj, strict=False)
    except json.JSONDecodeError as e:
        raise ValueError(f"plan JSON invalid: {e}") from e
    data.setdefault("post_slots", [])
    data.setdefault("cited_numbers", [])
    data.setdefault("recommended_posts", None)
    data.setdefault("cadence_why", "")
    if not isinstance(data.get("post_slots"), list):
        raise ValueError("post_slots must be a list")
    _check_type_mix(data["post_slots"])
    _check_merchants(data["post_slots"], available_merchants)
    return data


def _check_merchants(slots: list[dict], available_merchants: list[str] | None) -> None:
    """The prompt tells the model every slot's merchant MUST come from
    AVAILABLE_MERCHANTS (the real live deal feed's vocabulary — see
    build_plan_context). If it still invents one (e.g. "shopsy", which our
    scraper never collects — see ALLOWED_MERCHANTS in deal_scraper.py), jit_fill
    can't match it to a real deal and silently broadens to a different merchant,
    so the schedule the operator sees would show a merchant that will never
    actually post. Reject so the caller falls back to the deterministic plan,
    same pattern as _check_type_mix."""
    if not available_merchants:
        return
    avail = {m.lower() for m in available_merchants}
    for sl in slots:
        merchant = (sl.get("merchant") or "").strip().lower()
        if merchant and merchant not in avail:
            raise ValueError(
                f"slot merchant {merchant!r} is not in today's live deal feed "
                f"{sorted(avail)} — model invented a merchant we don't collect")


def _check_type_mix(slots: list[dict]) -> None:
    """G3 HARD variety floor. The prompt asks for a loot/single mix with a 30% floor per
    type (_MIN_TYPE_SHARE — same floor the deterministic fallback enforces by construction);
    if the model collapses a day with enough slots (>=4) into a single type, OR drifts one
    type below that floor while technically including both, we reject the plan (raise) so
    parse_plan's caller falls back to the deterministic plan. Previously this only checked
    "at least 2 types present", so a plan could pass with e.g. 86%/14% single/loot (a real
    case seen live) — technically mixed, but not the mix the prompt/floor actually asks
    for. Previously-previously this only logged, so 100%-single days shipped anyway."""
    total = sum(max(int(sl.get("count") or 1), 1) for sl in slots)
    if total < 4:
        return
    counts: dict[str, int] = {}
    for sl in slots:
        t = sl.get("type") or "single"
        counts[t] = counts.get(t, 0) + max(int(sl.get("count") or 1), 1)
    if len(counts) < 2:
        logger.warning(
            "[ai.planner] day plan collapsed to type(s) %r across %d slots — rejecting so "
            "the floor-enforcing deterministic fallback runs instead", counts, total)
        raise ValueError(
            f"day plan collapsed to a single type {counts} across {total} slots — "
            "violates the loot/single variety floor")
    minority_share = min(counts.values()) / total
    if minority_share < _MIN_TYPE_SHARE:
        logger.warning(
            "[ai.planner] day plan skews to %r across %d slots (minority share %.0f%%, "
            "floor is %.0f%%) — rejecting so the floor-enforcing deterministic fallback "
            "runs instead", counts, total, minority_share * 100, _MIN_TYPE_SHARE * 100)
        raise ValueError(
            f"day plan minority type share {minority_share:.0%} across {counts} "
            f"({total} slots) is below the {_MIN_TYPE_SHARE:.0%} variety floor")


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


def _fallback_day_plan(day, plan_ctx: dict) -> dict:
    """G6 — a REAL deterministic day plan for when the AI call fails or returns
    something unparseable. The channel must never go silent on an AI outage, so this
    covers every POSTING_WINDOW from ``plan_ctx`` (already computed for the AI call),
    splits each window's slots between `single`/`collection` by the week's
    loot_deal_ratio (or the same 60/40 single-lean default + 30% floor the prompt
    uses), and assigns merchants/categories straight from the already-ranked
    MERCHANT_MIX/available categories. Marked ``is_fallback`` so callers/persist
    know it's a stand-in, not a grounded plan."""
    windows = plan_ctx.get("posting_windows") or []
    # merchant_mix ranks by HISTORICAL posting share, which can include a merchant
    # no longer in today's live deal feed (e.g. the scraper's allowed retailers
    # narrowed since those posts went out) — jit_fill could never actually fill
    # such a slot, so a slot assigned that merchant would show a merchant that
    # will never really post (same failure mode _check_merchants guards against
    # on the AI path). Keep merchant_mix's ranking but restrict to what's real
    # today; fall back to the live feed unranked if none of the ranked ones remain.
    available_merchants = set(plan_ctx.get("available_merchants") or [])
    ranked_merchants = [m["merchant"] for m in (plan_ctx.get("merchant_mix") or []) if m.get("merchant")]
    merchants = [m for m in ranked_merchants if m in available_merchants] or sorted(available_merchants)
    categories = plan_ctx.get("available_categories") or []
    recommended = int(plan_ctx.get("recommended_posts")
                       or sum((w.get("posts") or 0) for w in windows) or 1)

    direction = plan_ctx.get("this_week_direction") or {}
    ratio = direction.get("loot_deal_ratio") or {}
    loot_n, single_n = ratio.get("loot"), ratio.get("deal")
    if loot_n or single_n:
        total_r = (loot_n or 0) + (single_n or 0) or 1
        loot_share = (loot_n or 0) / total_r
        ratio_basis = "this week's loot_deal_ratio"
    else:
        loot_share = _DEFAULT_LOOT_SHARE
        ratio_basis = "the default 60/40 single-lean split (no week direction yet)"
    loot_share = min(max(loot_share, _MIN_TYPE_SHARE), 1 - _MIN_TYPE_SHARE)

    if not windows:
        windows = [{"part": "all day", "hours": "09:00-21:00", "posts": recommended}]
    win_total = sum(max(int(w.get("posts") or 0), 0) for w in windows) or len(windows)

    slots = []
    why = (f"FALLBACK PLAN (AI unavailable) — deterministic split holding {ratio_basis} "
           f"(~{loot_share:.0%} loot) with the 30%-floor; merchant/category picked by "
           "recent share from MERCHANT_MIX, not model reasoning. Regenerate once the AI "
           "planner is back for a grounded, per-slot rationale.")
    for i, w in enumerate(windows):
        n = max(round((w.get("posts") or 0) * recommended / win_total), 1) if win_total else 1
        loot_c = min(max(round(n * loot_share), 0), n)
        single_c = n - loot_c
        hours = w.get("hours") or "09:00-21:00"
        merchant = merchants[i % len(merchants)] if merchants else ""
        category = categories[i % len(categories)] if categories else ""
        if single_c > 0:
            slots.append({"type": "single", "window_ist": hours, "count": single_c,
                          "theme": category, "merchant": merchant, "max_price": None,
                          "why": why})
        if loot_c > 0:
            slots.append({"type": "collection", "window_ist": hours, "count": loot_c,
                          "theme": category, "merchant": merchant, "max_price": None,
                          "why": why})
    return {
        "date": day.isoformat(), "recommended_posts": recommended,
        "cadence_why": "AI unavailable — holding the recent posting cadence deterministically.",
        "post_slots": slots,
        "emphasis": "keep posting — deterministic fallback active",
        "watch": "regenerate once the AI planner is back for a grounded plan",
        "cited_numbers": [], "is_fallback": True,
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
        raw = ai.complete(user, system_extra=_DAILY_PLAN_SYSTEM, max_tokens=3200,
                          trace_call="day_plan")
    except AIUnavailable as e:
        # G6 — never go silent: the channel still needs slots even when the AI is
        # down, so fall back to a real deterministic plan instead of an empty one.
        logger.warning("[ai.planner] AI unavailable for day plan (%s) — using "
                       "deterministic fallback", e)
        fallback = _fallback_day_plan(day, plan_ctx)
        return {"available": True, "digest": "AI planner unavailable "
                f"({e}) — a deterministic fallback plan is active (covers every "
                "posting window with a loot/single mix); regenerate once the AI "
                "is back for a grounded plan.", "plan": fallback, "facts": facts,
                "is_fallback": True}
    digest, plan_text = _split_digest_and_plan(raw)
    try:
        plan = parse_plan(plan_text, plan_ctx.get("available_merchants"))
    except ValueError:
        logger.warning("[ai.planner] unparseable day plan output — using "
                       "deterministic fallback")
        fallback = _fallback_day_plan(day, plan_ctx)
        return {"available": True, "digest": digest or (
                "AI planner returned an unparseable plan — a deterministic "
                "fallback plan is active; regenerate once the AI is back for a "
                "grounded plan."), "plan": fallback, "facts": facts, "is_fallback": True}
    _repair_merchant_diversity(plan.get("post_slots") or [], plan_ctx.get("available_merchants"))
    return {"available": True, "digest": digest, "plan": plan, "facts": facts}


def _parse_week_plan(raw: str) -> dict:
    obj = _extract_json_object(raw)
    if obj is None:
        raise ValueError("no JSON object found in model output")
    try:
        # strict=False: the model occasionally embeds a raw control character
        # inside a string value (e.g. a stray byte in a "why" field) — valid
        # enough to mean, invalid per strict JSON's ban on unescaped control
        # chars in strings. That was rejecting a real, well-formed plan and
        # falling back to the generic deterministic one ~1 in 4-8 generations.
        data = json.loads(obj, strict=False)
    except json.JSONDecodeError as e:
        raise ValueError(f"weekly plan JSON invalid: {e}") from e
    data.setdefault("daily_themes", [])
    data.setdefault("cited_numbers", [])
    if not isinstance(data["daily_themes"], list):
        raise ValueError("daily_themes must be a list")
    for t in data["daily_themes"]:
        if not isinstance(t, dict):
            continue
        # G2: daily_themes carries a per-day loot/single SPLIT now, not a single
        # theme_focus label — fill in whichever share the model left out so every
        # reader downstream (the daily prompt's THIS_WEEK_THEME) always sees both.
        loot, single = t.get("loot_share"), t.get("single_share")
        if loot is None and single is None:
            loot, single = _DEFAULT_LOOT_SHARE, 1 - _DEFAULT_LOOT_SHARE
        elif loot is None:
            loot = 1 - single
        elif single is None:
            single = 1 - loot
        t["loot_share"], t["single_share"] = round(loot, 3), round(single, 3)
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
        raw = ai.complete(user, system_extra=_WEEKLY_PLAN_SYSTEM, max_tokens=2000,
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
    # FIX 1 (weekly) — same prose fact-check as the daily path: `cited_numbers` is
    # always empty (the model never fills it in), so what needs checking is the
    # PROSE (digest + direction + each day's why/theme text) against the facts it
    # was grounded on, with the plan's own decision numbers (loot_deal_ratio,
    # posts_planned, loot/single share) excluded as self-valid structural numbers.
    from src.ai.factcheck import check_cited_numbers, extract_prose_numbers, plan_structural_numbers
    structural = plan_structural_numbers(plan)
    facts_pool = [*facts, {f"s{i}": v for i, v in enumerate(structural)}]
    fc = check_cited_numbers(extract_prose_numbers({**plan, "digest": digest}), facts_pool)
    return {"available": True, "digest": digest, "plan": plan, "facts": facts, "factcheck": fc}


def _demo() -> None:
    """Runnable self-check (no DB): parse_plan + its type-mix nudge, the weekly
    loot/single-share normalization, and the deterministic fallback actually
    mixing both types across windows."""
    from collections import Counter
    from datetime import date

    # trailing content after the real object (e.g. a stray aside with its own
    # '}') must not get swallowed into "Extra data" — see _extract_json_object.
    trailing = _extract_json_object('noise {"a": {"b": 1}} more noise } and }')
    assert trailing == '{"a": {"b": 1}}', trailing

    plan = parse_plan(
        '{"date":"2026-07-21","recommended_posts":9,"cadence_why":"x",'
        '"post_slots":[{"type":"single","window_ist":"09:00-12:00","count":6,'
        '"theme":"electronics","merchant":"amazon","max_price":null,"why":"x"},'
        '{"type":"collection","window_ist":"18:00-21:00","count":3,'
        '"theme":"fashion","merchant":"ajio","max_price":null,"why":"x"}],'
        '"emphasis":"e","watch":"w","cited_numbers":[]}'
    )
    assert plan["recommended_posts"] == 9
    assert len(plan["post_slots"]) == 2  # a real mix (minority share 3/9=33% clears the 30% floor)

    skewed_raw = (
        '{"date":"2026-07-21","recommended_posts":8,"cadence_why":"x",'
        '"post_slots":[{"type":"single","window_ist":"09:00-12:00","count":7,'
        '"theme":"electronics","merchant":"amazon","max_price":null,"why":"x"},'
        '{"type":"collection","window_ist":"18:00-21:00","count":1,'
        '"theme":"fashion","merchant":"ajio","max_price":null,"why":"x"}],'
        '"emphasis":"e","watch":"w","cited_numbers":[]}'
    )
    try:
        parse_plan(skewed_raw)  # minority share 1/8=12.5%, below the 30% floor
        raise AssertionError("expected a below-floor type skew to be rejected")
    except ValueError:
        pass

    same_raw = (
        '{"date":"2026-07-21","recommended_posts":8,"cadence_why":"x",'
        '"post_slots":[{"type":"single","window_ist":"09:00-12:00","count":8,'
        '"theme":"electronics","merchant":"shopsy","max_price":null,"why":"x"}],'
        '"emphasis":"e","watch":"w","cited_numbers":[]}'
    )
    try:
        parse_plan(same_raw, available_merchants=["amazon", "flipkart", "myntra", "ajio"])
        raise AssertionError("expected merchant not in feed to be rejected")
    except ValueError:
        pass

    week = _parse_week_plan(
        '{"week_start":"2026-07-20","direction":"d",'
        '"loot_deal_ratio":{"loot":4,"deal":6},"merchant_priorities":[],'
        '"daily_themes":[{"day":"mon","single_share":0.7,"posts_planned":8}],'
        '"why":"w","cited_numbers":[]}'
    )
    mon = week["daily_themes"][0]
    assert abs(mon["loot_share"] - 0.3) < 1e-6
    assert abs(mon["single_share"] - 0.7) < 1e-6

    ctx = {
        "posting_windows": [{"part": "morning", "hours": "09:00-12:00", "posts": 4},
                            {"part": "evening", "hours": "18:00-21:00", "posts": 4}],
        "merchant_mix": [{"merchant": "amazon"}, {"merchant": "flipkart"}],
        "available_merchants": ["amazon", "flipkart"],
        "available_categories": ["electronics", "fashion"],
        "recommended_posts": 8,
        "this_week_direction": {"loot_deal_ratio": {"loot": 4, "deal": 6}},
    }
    fb = _fallback_day_plan(date.fromisoformat("2026-07-21"), ctx)
    assert fb["is_fallback"] is True
    types = {sl["type"] for sl in fb["post_slots"]}
    assert types == {"single", "collection"}, f"fallback did not mix types: {types}"
    assert sum(sl["count"] for sl in fb["post_slots"]) == 8

    # no week direction / no merchant/category data at all — still real, still mixed
    fb2 = _fallback_day_plan(date.fromisoformat("2026-07-21"), {
        "posting_windows": [{"hours": "09:00-12:00", "posts": 5},
                            {"hours": "18:00-21:00", "posts": 5}],
        "recommended_posts": 10,
    })
    assert {sl["type"] for sl in fb2["post_slots"]} == {"single", "collection"}
    assert all(sl["merchant"] == "" and sl["theme"] == "" for sl in fb2["post_slots"])

    # FIX 3 — merchant diversity repair. 10 all-amazon slots across 2 windows (5
    # each) + 3 available merchants: no window should collapse to one merchant,
    # and amazon's day-wide share should land at the 40% cap, not run away.
    slots10 = ([{"window_ist": "morning", "merchant": "amazon"} for _ in range(5)]
              + [{"window_ist": "evening", "merchant": "amazon"} for _ in range(5)])
    _repair_merchant_diversity(slots10, ["amazon", "flipkart", "myntra"])
    by_win: dict[str, set] = {}
    for sl in slots10:
        by_win.setdefault(sl["window_ist"], set()).add(sl["merchant"])
    assert all(len(v) > 1 for v in by_win.values()), by_win  # no single-merchant window
    counts = Counter(sl["merchant"] for sl in slots10)
    assert counts["amazon"] / len(slots10) <= _MAX_MERCHANT_SHARE, counts

    # only 1 merchant in today's feed — a genuine constraint, leave untouched.
    slots_single = [{"window_ist": "morning", "merchant": "amazon"} for _ in range(3)]
    _repair_merchant_diversity(slots_single, ["amazon"])
    assert all(sl["merchant"] == "amazon" for sl in slots_single)

    print("ai/planner.py self-check OK")


if __name__ == "__main__":
    _demo()
