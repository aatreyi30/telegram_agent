"""AI analyst + planner. Reads DailyChannelReport rows, emits a grounded digest
+ structured day plan. AIClient has no JSON mode, so we prompt for JSON and
parse defensively; numbers are fact-checked downstream (ai/factcheck.py)."""
from __future__ import annotations

import json
import re

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


_HHMM_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _slot_minute(sl: dict) -> int | None:
    """Minutes-since-midnight parsed from a slot's per-post ``time_ist`` (new
    shape) or, for a legacy slot, the first HH:MM in its ``window_ist`` span.
    None if neither parses — the caller keeps such a slot's original list
    position as a fallback ordering."""
    raw = sl.get("time_ist") or sl.get("window_ist") or ""
    m = _HHMM_RE.search(raw)
    if not m:
        return None
    return (int(m.group(1)) % 24) * 60 + int(m.group(2)) % 60


def _feed_pairs(available_deals: list[dict] | None) -> dict[tuple[str, str], int]:
    """(merchant, category) -> live-feed deal count, from ``plan_ctx["available_deals"]``
    (see ``ai/context.py:available_deals``). The only source of truth for which
    merchant/category pairings the feed can actually fill — a slot paired outside
    this set is one ``jit_fill`` can never satisfy. Used both to build the
    fallback plan's rotation and to keep ``_repair_plan_diversity``'s
    reassignments feed-valid."""
    counts: dict[tuple[str, str], int] = {}
    for d in available_deals or []:
        m, c = d.get("merchant_key"), d.get("category")
        if m and c:
            counts[(m, c)] = counts.get((m, c), 0) + 1
    return counts


def _pair_sequence(pair_counts: dict[tuple[str, str], int]) -> list[tuple[str, str]]:
    """A round-robin (merchant, category) rotation from ``_feed_pairs``: cycle
    merchants ordered by total stock (deepest first), and within each merchant
    cycle its own categories (deepest first) one step per lap. This visits
    every real pairing once — deepest merchants/categories first — before any
    pairing repeats, so a 12-post day spans far more than
    ``max(len(merchants), len(categories))`` distinct pairs, and a merchant
    only ever gets a category it genuinely stocks."""
    if not pair_counts:
        return []
    by_merchant: dict[str, dict[str, int]] = {}
    for (m, c), n in pair_counts.items():
        by_merchant.setdefault(m, {})[c] = n
    merchant_order = sorted(by_merchant, key=lambda m: (-sum(by_merchant[m].values()), m))
    cat_cycles = {m: [c for c, _ in sorted(by_merchant[m].items(), key=lambda kv: (-kv[1], kv[0]))]
                  for m in merchant_order}
    idx = {m: 0 for m in merchant_order}
    seq: list[tuple[str, str]] = []
    total = sum(len(v) for v in cat_cycles.values())
    while len(seq) < total:
        for m in merchant_order:
            if idx[m] < len(cat_cycles[m]):
                seq.append((m, cat_cycles[m][idx[m]]))
                idx[m] += 1
    return seq


def _repair_plan_diversity(slots: list[dict], available_merchants: list[str] | None,
                            available_categories: list[str] | None = None,
                            available_pairs: set[tuple[str, str]] | dict[tuple[str, str], int] | None = None
                            ) -> None:
    """Enforce merchant AND theme rotation the prompt only asks for (a run of
    slots otherwise comes back one merchant/category in a row). Renamed from
    ``_repair_merchant_diversity`` now that it balances both dimensions.
    Operates on the slots' CHRONOLOGICAL order (parsed via ``_slot_minute``),
    not window grouping — with one-slot-per-post there's no window bucket left
    to group by, and a legacy plan's slots are already chronological by list
    order. Keeps the model's merchant unless it repeats the chronologically
    PRIOR slot, isn't in today's feed, or exceeds ``_MAX_MERCHANT_SHARE``;
    keeps the model's theme unless it repeats the prior slot's theme and an
    alternative category is available — reassigning the fewest slots
    possible. A reassigned slot's ``why`` was written for the OLD merchant/
    theme, so overwrite it with a number-free rotation note (else the text
    contradicts the data). No-op on a dimension with <2 available options (a
    feed constraint). ``available_pairs`` (optional, keyword-only — new
    callers can pass it, ``ai_execution.py``'s existing positional 3-arg call
    stays valid and unconstrained) is the set of (merchant, category) pairs
    the live feed can actually fill (``_feed_pairs``); when given, a
    reassignment is only made into a pairing that's actually stocked — if no
    valid alternative exists the slot is left as-is rather than stranded on
    an impossible combination. ``available_pairs`` may instead be a
    ``{pair: live_deal_count}`` dict (``_feed_pairs``'s own return shape,
    which a plain membership check still works against) — when it is, a
    pairing already carrying as many slots as it has deals is ALSO treated
    as a violation eligible for reassignment (same soft-cap-then-last-resort
    shape as the merchant cap below), and the reassignment target prefers
    deeper-stocked pairings. A bare ``set`` (no counts) skips this stock
    check — unconstrained by depth, same as before.

    A single slot is one (merchant, theme) PAIR, but merchant and theme were
    historically repaired in two independent passes, one dimension at a
    time. That deadlocks when ``available_pairs`` is small (e.g. exactly 2
    pairs that differ in BOTH dimensions): moving merchant alone lands on a
    pairing not in the set, so the move is rejected and the slot is left
    unchanged — same for theme alone — even though alternating the PAIR as a
    whole is perfectly valid. So both dimensions are now resolved together,
    per slot, in one chronological pass: try keeping the model's pick, else
    the smallest single-dimension move that stays inside ``available_pairs``
    (as before), and only when that alone can't clear the adjacency
    violation, fall back to swapping to a different valid PAIR (moving both
    fields together). Keep -> single-dimension move -> pair swap -> keep as
    a last resort (never stranded on an invalid pair)."""
    if not slots:
        return
    ordered = sorted(slots, key=lambda sl: (_slot_minute(sl) is None, _slot_minute(sl) or 0))
    changed: dict[int, list[str]] = {}

    def _pair_ok(m: str | None, c: str | None) -> bool:
        return available_pairs is None or not m or not c or (m, c) in available_pairs

    # Stock depth, when ``available_pairs`` was handed the ``_feed_pairs`` dict rather
    # than a bare set — {} (falsy) for a set or None, which disables every depth check
    # below exactly like today (a plain set carries no count information to check).
    pair_counts: dict[tuple[str, str], int] = (
        available_pairs if isinstance(available_pairs, dict) else {})
    pair_used: dict[tuple[str, str], int] = {}

    merchants = [m for m in (available_merchants or []) if m]
    categories = [c for c in (available_categories or []) if c]
    do_merchant = len(merchants) >= 2
    do_theme = len(categories) >= 2
    if not do_merchant and not do_theme:
        return

    cap = max(round(len(slots) * _MAX_MERCHANT_SHARE), 1) if do_merchant else None
    counts: dict[str, int] = {m: 0 for m in merchants} if do_merchant else {}
    prev_m: str | None = None
    prev_c: str | None = None

    for sl in ordered:
        cur_m, cur_c = sl.get("merchant"), sl.get("theme")
        m, c = cur_m, cur_c

        merchant_ok = (not do_merchant) or (cur_m in counts and cur_m != prev_m and counts[cur_m] < cap)
        if do_merchant and not merchant_ok:
            eligible = [x for x in merchants if counts[x] < cap] or merchants
            pick_from = [x for x in eligible if x != prev_m] or eligible
            valid = [x for x in pick_from if _pair_ok(x, cur_c)]
            if valid:
                m = min(valid, key=lambda x: counts.get(x, 0))

        theme_ok = (not do_theme) or not (cur_c and cur_c == prev_c)
        if do_theme and not theme_ok:
            candidates = [x for x in categories if x != cur_c and _pair_ok(m, x)]
            if candidates:
                c = candidates[0]

        # Single-dimension moves above still leave a violation exactly when no
        # in-pool move stays inside available_pairs (the deadlock case) — fall back
        # to swapping the whole pair. A merchant AT its cap (not just repeating the
        # prior slot) counts too — the single-dimension move above may have found no
        # feed-valid merchant to move to and silently kept `m` over cap; escalating
        # here is what lets a pair swap (which can also move theme) find a compliant
        # combination the single-dimension search couldn't. Same for a pairing
        # already at its live-deal ceiling (``pair_counts``, when given).
        merchant_violates = do_merchant and (m == prev_m or counts.get(m, 0) >= cap)
        theme_violates = do_theme and c and c == prev_c
        pair_violates = bool(pair_counts) and m and c and (
            pair_used.get((m, c), 0) >= pair_counts.get((m, c), 0))
        if available_pairs is not None and (merchant_violates or theme_violates or pair_violates):
            def _in_scope(p: tuple[str, str]) -> bool:
                pm_ok = (p[0] != prev_m) if do_merchant else (p[0] == cur_m)
                pc_ok = (p[1] != prev_c) if do_theme else (p[1] == cur_c)
                return pm_ok and pc_ok

            cands = [p for p in available_pairs if _in_scope(p)]
            if do_merchant:
                capped = [p for p in cands if counts.get(p[0], 0) < cap]
                cands = capped or cands
            if pair_counts:
                stocked = [p for p in cands if pair_used.get(p, 0) < pair_counts.get(p, 0)]
                cands = stocked or cands
            if cands:
                cands.sort(key=lambda p: (
                    0 if p[0] == m else 1,
                    0 if p[1] == c else 1,
                    -pair_counts.get(p, 0) if pair_counts else 0,
                    counts.get(p[0], 0) if do_merchant else 0,
                    p,
                ))
                m, c = cands[0]

        if m != cur_m:
            sl["merchant"] = m
            changed.setdefault(id(sl), []).append("merchant")
        if c != cur_c:
            sl["theme"] = c
            changed.setdefault(id(sl), []).append("theme")

        if do_merchant:
            counts[m] = counts.get(m, 0) + 1
        if pair_counts and m and c:
            pair_used[(m, c)] = pair_used.get((m, c), 0) + 1
        prev_m, prev_c = m, c

    for sl in ordered:
        keys = changed.get(id(sl))
        if keys:
            sl["why"] = (
                f"{sl.get('merchant') or 'Deal'} · {sl.get('theme') or 'general'} post — "
                f"{' and '.join(keys)} varied so the day doesn't repeat the same "
                "merchant/category back-to-back, widening reach across the audience."
            )


# A comma immediately before a closing } or ] (optionally across whitespace) — an
# LLM JSON habit that strict json rejects. ``strict=False`` forgives control chars
# but NOT this, so a single trailing comma sank a whole (otherwise valid) plan.
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _loads_lenient(obj: str) -> dict:
    """``json.loads`` tolerant of the two model quirks that reject a real plan:
    unescaped control chars in a string (``strict=False``) and a trailing comma
    before ``}``/``]`` (stripped first). ponytail: the comma regex could in theory
    touch a literal ', }' inside a string value — vanishingly rare in prose whys;
    upgrade to a real tokenizer only if that ever actually bites."""
    return json.loads(_TRAILING_COMMA_RE.sub(r"\1", obj), strict=False)


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
        # Tolerant load: forgives a stray control char in a "why" AND a trailing
        # comma before }/] — both are model habits that sank a real, well-formed
        # plan into the deterministic fallback ~1 in 4-8 generations.
        data = _loads_lenient(obj)
    except json.JSONDecodeError as e:
        raise ValueError(f"plan JSON invalid: {e}") from e
    data.setdefault("post_slots", [])
    data.setdefault("cited_numbers", [])
    data.setdefault("recommended_posts", None)
    data.setdefault("cadence_why", "")
    if not isinstance(data.get("post_slots"), list):
        raise ValueError("post_slots must be a list")
    # Canonicalize the slot `type` to the prompt's single|collection vocabulary BEFORE
    # any counting. gpt-4o-mini drifts to "loot_deal"/"single_deal" (see constants.py),
    # and the floor guard + _lock_type_split compare raw strings — so a mixed vocabulary
    # split loot across two labels, letting a skewed plan pass the 30% floor and making
    # the padding miscount loot (the "3 single / 36 loot" bug). One label, one truth.
    from src.services.generation.constants import is_loot_type
    for _sl in data["post_slots"]:
        if isinstance(_sl, dict):
            _sl["type"] = "collection" if is_loot_type(_sl.get("type")) else "single"
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
    # The PRIOR plan's free-text digest carries its OWN "Yesterday: posted N…, 5 loot"
    # recap whose numbers describe TWO days ago — the model kept copying those onto THIS
    # yesterday (a real mismatch: it wrote "5 loot deals" when yesterday had 22). Pass
    # only the prior plan's structured emphasis as the continuity signal (what it set out
    # to do), never its stale numeric prose. Yesterday's real numbers live in `yesterday`.
    _prior_bp = (yesterday_plan.blueprint or {}) if yesterday_plan is not None else {}
    _prior_note = _prior_bp.get("emphasis") or None
    ctx_dict = {
        "today": day.isoformat(),
        "day_of_week": day.strftime("%A"),
        "this_week_theme": _week_theme_for(day, week_bp),
        "this_week_direction": week_direction,
        "available_categories": available_categories,
        "available_merchants": available_merchants,
        "yesterday": yesterday,
        "yesterday_digest": _prior_note,
        "trajectory": traj["days"],
        "recent_cadence": recent_cadence,
        "lifetime_baseline": traj["lifetime_baseline"],
        "recommended_posts": recommended_posts,
        "posting_windows": inputs.get("posting_windows", []),
        "deal_type_allocation": inputs.get("deal_type_allocation", []),
        "merchant_mix": inputs.get("merchant_allocation", []),
        "post_type_performance": ctx.post_type_performance(s),
        "channel_style": ctx.channel_style(s),
        "segment_performance": ctx.segment_performance(s),
        "follower_trajectory": follower_trajectory,
        "style_follower_correlation": ctx.style_follower_correlation(s, days=14, end_day=prev),
        "competitor_benchmark": ctx.competitor_benchmark(s),
        "upcoming_event": inputs.get("upcoming_event"),
        "retro": ctx.latest_retro(s),
        "available_deals": available_deals,
        "operator_directive": directive,
    }
    # Views are whole numbers to a reader — round every view figure the model will see
    # to an integer so it can't cite "573.087 views". Both the prompt AND the fact-check
    # pool are built from this dict, so they stay mutually consistent. Rates/shares
    # (engagement_rate, *_ratio, share) are deliberately NOT rounded.
    _round_view_fields(ctx_dict)
    return ctx_dict


# View-count fields (a whole number of views) — rounded to int before the AI sees them.
# Excludes engagement_rate / shares / ratios, which are genuinely fractional.
_VIEW_KEYS = frozenset({
    "views", "views_avg", "views_total", "views_median", "views_max", "views_min",
    "avg_views", "avg_views_per_post", "avg_views_per_day", "median_views",
})


def _round_view_fields(obj) -> None:
    """Recursively round every view-count value (see ``_VIEW_KEYS``) to an int, in place."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _VIEW_KEYS and isinstance(v, float):
                obj[k] = int(round(v))
            else:
                _round_view_fields(v)
    elif isinstance(obj, list):
        for it in obj:
            _round_view_fields(it)


_WINDOW_SPAN_RE = re.compile(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})")


def _spread_times(hours: str, n: int) -> list[str]:
    """``n`` "HH:MM" IST times evenly spread across ``hours``'s "HH:MM-HH:MM"
    span (first at the window start, last at/before the end) — never bunched
    at the start the way a fixed-spacing burst would be. Falls back to a flat
    09:00 for every post if the span can't be parsed (mirrors the old
    "skip silently" safety, but the fallback plan must never emit zero posts,
    so it still emits ``n`` slots, just untimed-spread)."""
    if n <= 0:
        return []
    m = _WINDOW_SPAN_RE.match(hours or "")
    if not m:
        return ["09:00"] * n
    sh, sm, eh, em = (int(x) for x in m.groups())
    start, end = sh * 60 + sm, eh * 60 + em
    if end <= start or n == 1:
        return [f"{start // 60 % 24:02d}:{start % 60:02d}"] * n
    step = (end - start) / (n - 1)
    out = []
    for i in range(n):
        minute = round(start + step * i)
        out.append(f"{minute // 60 % 24:02d}:{minute % 60:02d}")
    return out


def _interleave_counts(counts: dict[str, int]) -> list[str]:
    """Evenly interleave labels by their counts (largest-remainder round robin)
    so e.g. 3 collection + 5 single comes out spread across the sequence
    instead of block-grouped ("collection,collection,collection,single,...").
    Used to mix `single`/`collection` across a window's spread-out posts."""
    total = sum(counts.values())
    out: list[str] = []
    acc = {k: 0.0 for k in counts}
    for _ in range(total):
        for k in acc:
            acc[k] += counts[k]
        k = max(acc, key=lambda x: acc[x])
        acc[k] -= total
        out.append(k)
    return out


def _fallback_day_plan(day, plan_ctx: dict) -> dict:
    """G6 — a REAL deterministic day plan for when the AI call fails or returns
    something unparseable. The channel must never go silent on an AI outage, so this
    covers every POSTING_WINDOW from ``plan_ctx`` (already computed for the AI call),
    splits each window's posts between `single`/`collection` by the week's
    loot_deal_ratio (or the same 60/40 single-lean default + 30% floor the prompt
    uses), spreads each window's posts across its full span (``_spread_times``,
    interleaved single/collection via ``_interleave_counts`` rather than
    block-grouped), and rotates (merchant, category) PAIRS PER POST (not per window)
    from ``available_deals`` — the real stocked pairings (``_feed_pairs``/
    ``_pair_sequence``), so a merchant only ever gets a category it genuinely
    carries, deepest pairings preferred, spanning variety rather than collapsing
    onto one bucket. Without ``available_deals`` (degraded feed context), falls
    back to the flat ``available_merchants``/``available_categories`` lists — but
    the two cycles advance at DIFFERENT rates so they never lock into a fixed
    per-index table (the defect this whole rotation exists to avoid). Marked
    ``is_fallback`` so callers/persist know it's a stand-in, not a grounded plan."""
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
    pairs = _pair_sequence(_feed_pairs(plan_ctx.get("available_deals")))
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
    post_idx = 0
    for w in windows:
        n = max(round((w.get("posts") or 0) * recommended / win_total), 1) if win_total else 1
        loot_c = min(max(round(n * loot_share), 0), n)
        single_c = n - loot_c
        hours = w.get("hours") or "09:00-21:00"
        if loot_c and single_c:
            types = _interleave_counts({"collection": loot_c, "single": single_c})
        elif loot_c:
            types = ["collection"] * loot_c
        else:
            types = ["single"] * single_c
        for t, tm in zip(types, _spread_times(hours, n)):
            if pairs:
                merchant, category = pairs[post_idx % len(pairs)]
            else:
                # ponytail: no available_deals to pair from — degrade to the flat
                # lists, but advance the category cycle at a different rate than
                # the merchant cycle (never post_idx % len for both) so equal-length
                # lists don't lock into one fixed per-index table. Doesn't guarantee
                # every category is reachable for every merchant; upgrade if a
                # degraded-feed day ever needs that guarantee.
                merchant = merchants[post_idx % len(merchants)] if merchants else ""
                # advance the category cycle at HALF the merchant cycle's rate — a
                # different divisor, not just a different offset, so equal-length
                # lists can't fall back into a fixed 1:1 per-index table.
                category = categories[(post_idx // 2) % len(categories)] if categories else ""
            slots.append({"type": t, "time_ist": tm, "theme": category, "merchant": merchant,
                          "max_price": None, "min_price": None, "why": why})
            post_idx += 1
    # The AI path runs the adjacency repair after parsing, but BOTH fallback returns in
    # generate_day_plan hand this plan straight back — so without this call an AI outage
    # is the one day nothing ever fixes adjacency. The pair walk above rotates merchants
    # cleanly but can still put two windows' posts of the same category side by side.
    # Feed-constrained, so a repair can't invent a pairing the feed won't fill.
    _pairs = _feed_pairs(plan_ctx.get("available_deals"))
    _repair_plan_diversity(slots, merchants or None, categories or None,
                           available_pairs=_pairs or None)
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
    # segment_performance's numbers (top/bottom category & discount-band
    # engagement rates) must be verifiable too — each row is its own top-level
    # fact item, same one-level-of-nesting reasoning as available_deals above.
    seg_perf = plan_ctx.get("segment_performance") or {}
    if seg_perf.get("available"):
        for _seg_key in ("top_categories", "bottom_categories",
                         "top_discount_bands", "bottom_discount_bands"):
            facts.extend(seg_perf.get(_seg_key) or [])
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
            "this constraint.\n"
            "ATTRIBUTION (honesty — do NOT dress the directive up as your own analysis): a "
            "choice you make ONLY because the operator asked for it must be attributed to the "
            "directive, e.g. 'per your steer, leaning electronics from Amazon/Flipkart'. NEVER "
            "justify a directive-driven choice with 'based on successful patterns' / 'the data "
            "shows' / 'historically strong' UNLESS a real figure in DATA actually supports it — "
            "and if it does, cite that number. If DATA does NOT support the directive (or is "
            "silent), say so plainly, e.g. 'this is your directive, not an evidence-led pick — "
            "Flipkart isn't independently a top performer in the data'. The reader must be able "
            "to tell which choices came from the data and which came from your instruction.\n"
            + directive
        )
    try:
        user = f"DATA:\n{to_json(plan_ctx)}{recon_note}{directive_note}"
        # The prompt requires ONE JSON object PER POST, each with a 3-4 sentence `why`
        # (~180 output tokens/slot). A fixed 3200-token cap truncated the JSON array for
        # high-cadence days (e.g. 39 posts -> unparseable / too-few-slots -> fallback
        # EVERY time). Fund the budget from the actual slot count so any cadence fits.
        _n_slots = plan_ctx.get("recommended_posts") or 10
        _budget = min(max(3200, _n_slots * 180 + 1500), 16000)
        raw = ai.complete(user, system_extra=_DAILY_PLAN_SYSTEM, max_tokens=_budget,
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
                "is_fallback": True,
                "feed_pairs": _feed_pairs(plan_ctx.get("available_deals"))}
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
                "grounded plan."), "plan": fallback, "facts": facts, "is_fallback": True,
                "feed_pairs": _feed_pairs(plan_ctx.get("available_deals"))}
    _feed_pair_counts = _feed_pairs(plan_ctx.get("available_deals"))
    _repair_plan_diversity(plan.get("post_slots") or [], plan_ctx.get("available_merchants"),
                           plan_ctx.get("available_categories"),
                           available_pairs=_feed_pair_counts or None)
    # Steer directive -> HARD constraints the diversity-repair can't express: PARSE the
    # merchants/categories an operator restricted, plus any time window, and stash them
    # on the plan. They're ENFORCED in persist_ai_plan AFTER all slot padding/
    # reconciliation — enforcing here would be undone when persist pads the plan up to
    # the cadence (the padding re-introduces dropped merchants). Constraints are matched
    # only against real feed values, so nothing is invented.
    if directive:
        from src.services.generation.directives import parse_directive_constraints
        _cons = parse_directive_constraints(
            directive, plan_ctx.get("available_merchants"), plan_ctx.get("available_categories"))
        if any(_cons.get(k) is not None for k in ("merchants", "categories",
               "exclude_merchants", "exclude_categories", "after_min", "before_min",
               "price_min", "price_max")):
            plan["_directive_constraints"] = {
                "merchants": sorted(_cons["merchants"]) if _cons["merchants"] else None,
                "categories": sorted(_cons["categories"]) if _cons["categories"] else None,
                "exclude_merchants": sorted(_cons["exclude_merchants"]) if _cons["exclude_merchants"] else None,
                "exclude_categories": sorted(_cons["exclude_categories"]) if _cons["exclude_categories"] else None,
                "after_min": _cons["after_min"], "before_min": _cons["before_min"],
                "price_min": _cons["price_min"], "price_max": _cons["price_max"]}
    return {"available": True, "digest": digest, "plan": plan, "facts": facts,
            "feed_pairs": _feed_pair_counts}


def _parse_week_plan(raw: str) -> dict:
    obj = _extract_json_object(raw)
    if obj is None:
        raise ValueError("no JSON object found in model output")
    try:
        # Tolerant load (control char + trailing comma) — see _loads_lenient.
        data = _loads_lenient(obj)
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


def generate_week_plan(s: Session, week_start=None, directive: str | None = None,
                       end_day=None) -> dict:
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

    facts_ctx = full_briefing_context(s, weekly=True, end_day=end_day)
    # --- Sanitize the weekly grounding before the model (and the fact-check pool built
    # from it) ever see it, so the narrative can't repeat three known distortions: ---
    # a) Integer views — no "573.087 views" in the prose.
    _round_view_fields(facts_ctx)
    # b) Drop follower deltas that span a capture GAP (spans_days > 1): a 14-day catch-up
    #    net (e.g. +1964) is NOT a single day's gain, and was being cited as a one-day
    #    win. Only genuine single-day measurements remain.
    _fd = facts_ctx.get("follower_deltas") or {}
    facts_ctx["follower_deltas"] = {d: v for d, v in _fd.items()
                                    if (v or {}).get("spans_days", 1) <= 1}
    # c) Strip avg_views_per_day from post-type performance: it's an age-confounded
    #    per-day VELOCITY that misranks the types (loot 39/day > single 13/day, yet
    #    single wins 779 > 569 per POST). Leaving only avg_views/_per_post forces the
    #    weekly read onto the honest metric — and stops it contradicting the daily plan.
    _by = {p["post_type"]: (p.get("avg_views") or 0) for p in facts_ctx.get("post_type_performance") or []}
    for _p in facts_ctx.get("post_type_performance") or []:
        _p.pop("avg_views_per_day", None)
        # `rank` encodes the per-day (loot-favoring) ordering — drop it too so nothing in
        # the post-type rows contradicts the per-post framing the weekly read must use.
        _p.pop("rank", None)
    # d) Pre-state the per-post winner DETERMINISTICALLY. gpt-4o-mini keeps reversing the
    #    comparison ("loot 569 beat single 779"); handing it the correct sentence to copy
    #    is far more reliable than a guardrail asking it to do the arithmetic right.
    _sv, _lv = _by.get("single_deal", 0), _by.get("loot_deal", 0)
    if _sv or _lv:
        _hi_t, _hi, _lo = (("single deals", round(_sv), round(_lv)) if _sv >= _lv
                           else ("loot boards", round(_lv), round(_sv)))
        _lo_t = "loot boards" if _hi_t == "single deals" else "single deals"
        facts_ctx["per_post_leader"] = (
            f"{_hi_t} lead on views PER POST ({_hi}) vs {_lo_t} ({_lo}). State the type "
            f"comparison in EXACTLY this direction — {_hi_t} performed better per post; "
            f"never say {_lo_t} out-viewed {_hi_t} per post.")
    # Flatten the new grounded signals into the fact-check pool as their own items so
    # cited style/follower/competitor numbers verify (nested lists inside facts_ctx are
    # otherwise invisible to check_cited_numbers, which flattens only one level).
    facts = [facts_ctx]
    # Flatten the nested LISTS in the briefing into their own top-level fact items —
    # check_cited_numbers only descends one level, so per-type/merchant numbers the
    # digest legitimately cites (e.g. a type's avg_views_per_day / a merchant's views)
    # were invisible to the pool and wrongly flagged as unverified, suppressing the
    # whole weekly narrative. Same flattening the daily plan already does.
    facts.extend(facts_ctx.get("post_type_performance") or [])
    facts.extend(facts_ctx.get("merchant_opportunities") or [])
    # The 7-day per-day series + totals must be in the pool so the digest can cite a real
    # day's posts/views (e.g. "37 posts, 542 views on Wed") without being flagged.
    facts.extend(facts_ctx.get("week_trajectory") or [])
    if facts_ctx.get("week_totals"):
        facts.append(facts_ctx["week_totals"])
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
    # FIX 1 (weekly) — same prose fact-check as the daily path: `cited_numbers` is
    # always empty (the model never fills it in), so what needs checking is the
    # PROSE (digest + direction + each day's why/theme text) against the facts it
    # was grounded on, with the plan's own decision numbers (loot_deal_ratio,
    # posts_planned, loot/single share) excluded as self-valid structural numbers.
    from src.ai.factcheck import check_cited_numbers, extract_prose_numbers, plan_structural_numbers
    # The gate is all-or-nothing (one invented figure hides the whole narrative), and
    # the small model drifts into a self-computed % / MoM figure ~half the time.
    # Standing prompt guardrails don't stop it; NAMING the exact offending number and
    # asking for a rewrite does. So: try once, and on a fail/warn retry ONCE with that
    # corrective note. Keep the better attempt; downstream still has the grounded
    # fallback for the rare double-miss. ponytail: 1 retry, raise the cap if it's still
    # failing too often (each retry is one extra call, only on a miss, cached per week).
    correction, best = "", None
    for _attempt in range(2):
        try:
            user = (f"WEEK_START: {week_start.isoformat()}\n\nDATA:\n"
                    f"{to_json(facts_ctx)}{directive_note}{correction}")
            raw = ai.complete(user, system_extra=_WEEKLY_PLAN_SYSTEM, max_tokens=2000,
                              trace_call="week_plan")
        except AIUnavailable as e:
            return best or {"available": False, "reason": str(e), "plan": None,
                            "digest": "", "facts": facts}
        digest, plan_text = _split_digest_and_plan(raw)
        try:
            plan = _parse_week_plan(plan_text)
        except ValueError:
            return best or {"available": False, "reason": "unparseable weekly plan",
                            "plan": None, "digest": digest, "facts": facts}
        plan.setdefault("week_start", week_start.isoformat())
        structural = plan_structural_numbers(plan)
        facts_pool = [*facts, {f"s{i}": v for i, v in enumerate(structural)}]
        fc = check_cited_numbers(extract_prose_numbers({**plan, "digest": digest}), facts_pool)
        best = {"available": True, "digest": digest, "plan": plan, "facts": facts,
                "factcheck": fc}
        if fc["status"] == "passed":
            break
        bad = ", ".join(str(round(u, 2)) for u in (fc.get("unverified") or []))
        correction = (
            "\n\nREWRITE REQUIRED: your previous draft cited number(s) that are NOT in "
            f"the DATA and cannot be verified: [{bad}]. Rewrite the digest and plan "
            "citing ONLY raw numbers that appear verbatim in the DATA above. Remove "
            "every percentage, week-over-week/month-over-month change, or ratio you "
            "computed yourself, and do not restate the offending number(s)."
        )
    return best


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

    # A trailing comma before ]/} (an LLM habit) must NOT sink an otherwise-valid plan.
    tc = parse_plan(
        '{"date":"2026-07-21","recommended_posts":2,"cadence_why":"x",'
        '"post_slots":[{"type":"single","time_ist":"09:00","theme":"e",'
        '"merchant":"amazon","why":"x"},],'  # <- trailing comma in the array
        '"emphasis":"e","watch":"w","cited_numbers":[1,2,],}'  # <- and in two objects
    )
    assert len(tc["post_slots"]) == 1, tc

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
    assert len(fb["post_slots"]) == 8  # AC6: one object per post, no `count` field
    assert all("count" not in sl and "time_ist" in sl for sl in fb["post_slots"])
    # AC6: spread, not bunched — the day's posts don't all land on one minute.
    times = [sl["time_ist"] for sl in fb["post_slots"]]
    assert len(set(times)) >= 2, times

    # no week direction / no merchant/category data at all — still real, still mixed
    fb2 = _fallback_day_plan(date.fromisoformat("2026-07-21"), {
        "posting_windows": [{"hours": "09:00-12:00", "posts": 5},
                            {"hours": "18:00-21:00", "posts": 5}],
        "recommended_posts": 10,
    })
    assert {sl["type"] for sl in fb2["post_slots"]} == {"single", "collection"}
    assert all(sl["merchant"] == "" and sl["theme"] == "" for sl in fb2["post_slots"])

    # AC1 — a per-post plan (new shape: `time_ist`, no `count`) parses and each
    # object counts as exactly one post.
    per_post_plan = parse_plan(
        '{"date":"2026-07-21","recommended_posts":4,"cadence_why":"x",'
        '"post_slots":[{"type":"single","time_ist":"09:05","theme":"electronics",'
        '"merchant":"amazon","max_price":null,"why":"x"},'
        '{"type":"single","time_ist":"10:40","theme":"fashion","merchant":"ajio",'
        '"max_price":null,"why":"x"},'
        '{"type":"collection","time_ist":"18:15","theme":"electronics",'
        '"merchant":"amazon","max_price":null,"why":"x"}],'
        '"emphasis":"e","watch":"w","cited_numbers":[]}'
    )
    assert len(per_post_plan["post_slots"]) == 3
    assert per_post_plan["post_slots"][0]["time_ist"] == "09:05"

    # AC4 — adjacency repair (renamed _repair_plan_diversity) now balances BOTH
    # merchant and theme, chronologically. A run of identical merchants gets broken.
    slots10 = [{"time_ist": f"{9 + i // 2:02d}:{(i % 2) * 30:02d}", "merchant": "amazon",
               "theme": "electronics"} for i in range(10)]
    _repair_plan_diversity(slots10, ["amazon", "flipkart", "myntra"], None)
    ordered10 = sorted(slots10, key=lambda sl: sl["time_ist"])
    assert all(ordered10[i]["merchant"] != ordered10[i + 1]["merchant"]
              for i in range(len(ordered10) - 1)), ordered10  # no back-to-back repeat
    counts = Counter(sl["merchant"] for sl in slots10)
    assert counts["amazon"] / len(slots10) <= _MAX_MERCHANT_SHARE, counts

    # A run of identical THEMES gets broken too, given >=2 available categories.
    theme_slots = [{"time_ist": f"{9 + i:02d}:00", "merchant": "amazon", "theme": "electronics"}
                  for i in range(4)]
    _repair_plan_diversity(theme_slots, None, ["electronics", "fashion"])
    assert all(theme_slots[i]["theme"] != theme_slots[i + 1]["theme"]
              for i in range(len(theme_slots) - 1)), theme_slots

    # only 1 merchant/category available — a genuine feed constraint, leave untouched.
    slots_single = [{"time_ist": f"{9 + i:02d}:00", "merchant": "amazon", "theme": "electronics"}
                    for i in range(3)]
    _repair_plan_diversity(slots_single, ["amazon"], ["electronics"])
    assert all(sl["merchant"] == "amazon" and sl["theme"] == "electronics" for sl in slots_single)

    print("ai/planner.py self-check OK")


if __name__ == "__main__":
    _demo()
