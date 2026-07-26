"""Just-in-time slot fill — the fresh-posting executor.

The AI daily plan (CampaignPlan.blueprint["post_slots"]) sets each post's window, type
(single/loot), theme, and merchant. Every minute this worker fills slots due within a
3-minute lookahead (plus a bounded backfill for slots recently missed — G9): scrape the
live pool, pick fresh item(s) matching theme/merchant (broadening on a miss), AI-write
single deals (deterministic template for loots and as fallback), then queue at the slot
time. Idempotent per slot via a tagged GeneratedPost. ~5 slots/day, evenly spread, are
picked deterministically to carry an image (§8b); the rest stay text-only.
"""

from __future__ import annotations

import math
import re
from collections import OrderedDict
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.services.affiliate import get_affiliate_provider
from src.services.automation.queue import IST, enqueue
from src.services.collection.deal_scraper import filter_relevant
from src.services.generation.constants import PRICE_FIELD_ALIASES, is_loot_type
from src.services.generation.deal_source import DealSourceClient, _map_item
from src.services.generation.enrichment import DealEnrichmentEngine
from src.services.generation.formatting import PostFormatter, _loot_label
from src.services.generation.strategy import PostingStrategy
from src.services.generation.daily_planner import recently_used_urls
from src.services.analytics.periods import ist_day_bounds_utc
from src.config.settings import get_settings
from src.db.models import Channel
from src.db.models_campaign import CampaignPlan, PlanType
from src.db.models_generation import GeneratedPost, PostStatus
from src.db.models_prediction import PostPrediction
from src.services.analytics.prediction import MODEL_VERSION, predict_for_slot
from src.logger import get_logger

logger = get_logger(__name__)

LOOKAHEAD_MIN = 3      # fill a slot this many minutes before it fires
BACKFILL_MIN = 30      # G9: also fill slots that fired up to this long ago, once
SPACING_MIN = 2        # gap between consecutive posts sharing one window
_SLOT_TAG = "aislot"   # GeneratedPost.selection_bucket prefix marking a filled slot
LOOT_ITEMS_PER_POST = 10  # distinct categories bundled into one loot post
IMAGE_POSTS_PER_DAY = 5   # §8b: image budget — this many posts/day carry a photo
# ponytail: cap (ceil) on any one merchant's share of a loot board — a loot spans
# several STORES, not one store's catalogue. Tune here.
LOOT_MERCHANT_CAP_FRACTION = 0.5

_HHMM = re.compile(r"(\d{1,2}):(\d{2})")


def _hhmm_all(s: str) -> list[time]:
    """Every HH:MM in `s`, as IST times. Invalid hours are dropped, not clamped —
    a plan that says "25:00" has a broken window, and silently reading it as 01:00
    would schedule posts at the wrong end of the day."""
    out = []
    for m in _HHMM.finditer(s or ""):
        hh, mm = int(m.group(1)), int(m.group(2))
        if hh < 24 and mm < 60:
            out.append(time(hh, mm))
    return out


def _window_start(window_ist: str) -> time | None:
    times = _hhmm_all(window_ist)
    return times[0] if times else None


def _window_span(window_ist: str) -> tuple[time, time] | None:
    """(start, end) of a "HH:MM-HH:MM" window. A window with only one time, or whose
    end is not after its start, has no usable span — the caller falls back to minimum
    spacing rather than inventing an end time."""
    times = _hhmm_all(window_ist)
    if len(times) < 2 or times[1] <= times[0]:
        return None
    return times[0], times[1]


def _slot_fire_times(slot: dict, base_day) -> list[datetime]:
    """The IST-anchored UTC fire time of every post in `slot`.

    Two shapes are supported, because a stored plan outlives the prompt that wrote it:

    * **per-post** (`time_ist: "HH:MM"`) — the agent chose this exact minute for this
      exact post. One post, fired then. This is the shape the planner now emits.
    * **legacy window** (`window_ist` + `count`) — `count` posts spread EVENLY across
      the window's full span. This used to stack them `SPACING_MIN` apart from the
      window start, so a 5-post 09:00-12:00 window fired 09:00-09:08 and then went
      silent for three hours; the window's end time was parsed and discarded. Spreading
      across the real span is what makes a "window" an actual schedule.

    `SPACING_MIN` is now only a floor, so a narrow window or a large count can never
    put two posts on the same minute.
    """
    explicit = _hhmm_all(str(slot.get("time_ist") or ""))
    if explicit:
        return [datetime.combine(base_day, explicit[0], tzinfo=IST).astimezone(timezone.utc)]

    start = _window_start(slot.get("window_ist", ""))
    if start is None:
        return []
    n = max(1, int(slot.get("count") or 1))
    base = datetime.combine(base_day, start, tzinfo=IST)

    span = _window_span(slot.get("window_ist", ""))
    if span is None or n == 1:
        step = float(SPACING_MIN)
    else:
        end = datetime.combine(base_day, span[1], tzinfo=IST)
        # n posts across the span inclusive of both ends -> n-1 gaps.
        step = max((end - base).total_seconds() / 60 / (n - 1), SPACING_MIN)
    return [(base + timedelta(minutes=step * i)).astimezone(timezone.utc) for i in range(n)]


def _expand_slots(post_slots: list[dict], base_day) -> list[tuple[datetime, dict, int, int]]:
    """Each slot -> one entry per post it schedules, via `_slot_fire_times`. Returns
    (fire_utc, slot, slot_index, sub_index), skipping slots with no usable time.
    Pure — unit-tested in _selfcheck."""
    out: list[tuple[datetime, dict, int, int]] = []
    for si, slot in enumerate(post_slots or []):
        for sub, fire in enumerate(_slot_fire_times(slot, base_day)):
            out.append((fire, slot, si, sub))

    # SPACING_MIN as a global floor. `_slot_fire_times` keeps posts apart WITHIN one
    # slot, but nothing stops the planner emitting two slots on the same minute (the
    # model picks each time_ist independently), and two posts firing together is the
    # burst behaviour this whole change exists to remove. Walk in fire order and push
    # any collision to the previous post's time + SPACING_MIN. Deterministic, so a
    # slot's key/fire time doesn't drift between cron ticks.
    out.sort(key=lambda e: (e[0], e[2], e[3]))
    gap = timedelta(minutes=SPACING_MIN)
    for i in range(1, len(out)):
        earliest = out[i - 1][0] + gap
        if out[i][0] < earliest:
            fire, slot, si, sub = out[i]
            out[i] = (earliest, slot, si, sub)
    return out


def _image_slot_indices(n: int, k: int = IMAGE_POSTS_PER_DAY) -> set[int]:
    """`k` evenly-spaced positions in an ordered list of length `n` (all of them if
    `n <= k`). Pure + deterministic — the same plan always yields the same image
    slots, no runtime counter/race. Used against the day's FULL slot list, not the
    due-now subset, so the image slots don't shift with cron timing."""
    if n <= k:
        return set(range(n))
    return {min(round((i + 1) * n / (k + 1)), n - 1) for i in range(k)}


def _image_slot_keys(full_slots: list[tuple[datetime, dict, int, int]]) -> set[tuple[int, int]]:
    """(slot_index, sub_index) pairs — from `full_slots` (all of _expand_slots, not
    just due-now) — chosen as the day's ~5 image posts.

    Ordered by FIRE TIME, not by slot index: now that a window's posts spread across
    its whole span, plan order and chronological order diverge, and "evenly spaced
    image slots" only means anything along the day's real timeline."""
    ordered = sorted(full_slots, key=lambda e: e[0])
    idx = _image_slot_indices(len(ordered))
    return {(ordered[i][2], ordered[i][3]) for i in idx}


def _norm(v: str | None) -> str:
    """Fold a category/merchant label to a comparable token: lowercase, alphanumeric
    only ('Amazon' -> 'amazon', 'amazon_in' -> 'amazonin', 'Electronics' -> ...)."""
    return re.sub(r"[^a-z0-9]", "", (v or "").lower())


def _match(a: str | None, b: str | None) -> bool:
    """Loose equality between an item's value and the plan's requested value — the AI
    plan and the scraper don't share an exact vocabulary. Normalized-equal, or one
    contains the other (handles 'amazon' vs 'amazon_in') for non-trivial tokens."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    return na == nb or (len(na) >= 4 and len(nb) >= 4 and (na in nb or nb in na))


def _item_merchant(it: dict) -> str | None:
    return it.get("merchant_key") or it.get("retailer_key")


def _item_price(it: dict) -> float | None:
    for k in PRICE_FIELD_ALIASES:
        v = it.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _as_price(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


_RUPEE_RE = re.compile(r"₹\s?([\d,]+(?:\.\d+)?)")
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s?%")
# A coupon token the AI wrote as prose ("use code SAVE20", "Code: FLAT10") — same
# alphanumeric shape the deal's own "coupon:<code>" tag stores.
_COUPON_RE = re.compile(r"\bcode[:\s]+([A-Za-z0-9]{3,15})\b", re.IGNORECASE)


def _close(a: float, b: float, tolerance: float = 0.02) -> bool:
    if a == b:
        return True
    denom = abs(b) if b else 1.0
    return abs(a - b) / denom <= tolerance


def _deal_coupon(deal) -> str | None:
    for t in (getattr(deal, "tags", None) or []):
        if isinstance(t, str) and t.startswith("coupon:"):
            return t.split(":", 1)[1]
    return None


def _copy_matches_deal(text: str, deal) -> bool:
    """Precision guard: every rupee figure and every percent figure the AI wrote in a
    single-deal post must match the real deal's own price/discount within 2% —
    never trust that the model copied a given number correctly without checking.
    The copywriter prompt only ever asks for THIS deal's price/discount, so a real
    mismatch means the model altered a number, not that it mentioned something else;
    numbers unmatched against the deal's own known figures fail closed (fall back to
    the template render) rather than being assumed fine. Deals missing a given figure
    (price or discount is None) skip that half of the check — nothing to compare.
    Same for a coupon: if the deal actually carries one (its `coupon:<code>` tag), the
    AI text must not invent a DIFFERENT code — a deal with no coupon at all skips
    that check too, same as a figure-less price/discount."""
    known_prices = {p for p in (deal.current_price, deal.original_price) if p}
    if known_prices:
        for m in _RUPEE_RE.finditer(text):
            val = float(m.group(1).replace(",", ""))
            if not any(_close(val, k) for k in known_prices):
                return False
    if deal.discount_percent:
        for m in _PCT_RE.finditer(text):
            val = float(m.group(1))
            if not _close(val, deal.discount_percent):
                return False
    coupon = _deal_coupon(deal)
    if coupon:
        for m in _COUPON_RE.finditer(text):
            if m.group(1).upper() != coupon.upper():
                return False
    return True


def _loot_copy_matches(text: str, deals: list, price_cap: float | None = None,
                      price_floor: float | None = None) -> bool:
    """Loot sibling of `_copy_matches_deal`: each ₹/% figure must match SOME item on
    the board (or the slot's price cap/floor). A figure-less board fails closed on any
    ₹/% — with real deals to cite, an unverifiable number is likely fabricated."""
    known_prices = {p for d in deals for p in (d.current_price, d.original_price) if p}
    known_prices |= {p for p in (price_cap, price_floor) if p}
    for m in _RUPEE_RE.finditer(text):
        val = float(m.group(1).replace(",", ""))
        if not (known_prices and any(_close(val, k) for k in known_prices)):
            return False
    known_discounts = {d.discount_percent for d in deals if d.discount_percent}
    for m in _PCT_RE.finditer(text):
        val = float(m.group(1))
        if not (known_discounts and any(_close(val, k) for k in known_discounts)):
            return False
    return True


def _in_band(it: dict, floor: float | None, cap: float | None) -> bool:
    """Price of `it` sits within [floor, cap] (either bound optional). A capped item
    must have a real positive price. Client-side safety net for the source price filter
    (the Camoufox fallback can't filter at source)."""
    p = _item_price(it) or 0
    if floor is not None and p < floor:
        return False
    if cap is not None and not (0 < p <= cap):
        return False
    return True


def _day_mix(s: Session, day) -> dict:
    """Fill-time diversity state for the given IST day, read back from
    `GeneratedPost.format_meta` — the only state that survives `jit_fill`'s separate
    per-tick invocations (unlike the in-run `used` set, which resets every minute).
    Returns merchant/theme counts of everything generated so far that day, plus the
    most recently generated post's merchant/theme (None before the day's first fill).
    """
    start, stop = ist_day_bounds_utc(day)
    merchant_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    last_merchant = last_category = None
    # S3-e: only jit_fill's own drafts carry the `aislot:` selection_bucket prefix —
    # drafts from other generation engines (controllers/jobs.py, the CLI generator)
    # must not pollute this worker's own diversity tallies.
    rows = s.scalars(select(GeneratedPost)
                     .where(GeneratedPost.generated_at >= start, GeneratedPost.generated_at < stop,
                            GeneratedPost.selection_bucket.like(f"{_SLOT_TAG}:%"))
                     .order_by(GeneratedPost.generated_at))
    for gp in rows:
        meta = gp.format_meta or {}
        merchant = meta.get("primary_merchant")
        # S1-b: the theme actually FILLED, not the plan's requested theme — a broadened
        # fill must not be tallied under a category it isn't. Falls back to the legacy
        # `slot.theme` echo for rows written before `primary_category` existed.
        category = meta.get("primary_category") or (meta.get("slot") or {}).get("theme")
        if merchant:
            key = _norm(merchant)
            merchant_counts[key] = merchant_counts.get(key, 0) + 1
            last_merchant = merchant
        if category:
            key = _norm(category)
            category_counts[key] = category_counts.get(key, 0) + 1
            last_category = category
    return {"merchant_counts": merchant_counts, "category_counts": category_counts,
            "last_merchant": last_merchant, "last_category": last_category}


def _deal_keys(it: dict) -> list[str]:
    """Every identifier that pins down this pool item: the source's own deal id first,
    then the URL. The id is stable across price moves; the URL is not (and a deal can
    resurface re-shortened or with different affiliate params), so matching on the URL
    alone let the same product post twice. Used for BOTH the repeat check and what we
    record as used, so the two can never key on different things."""
    return [str(v) for v in (it.get("external_id"), it.get("original_url")) if v]


def _pick_fresh(pool: list[dict], theme: str | None, merchant: str | None, used: set[str],
                merchant_counts: dict[str, int] | None = None,
                category_counts: dict[str, int] | None = None,
                prev_merchant: str | None = None,
                prev_category: str | None = None) -> tuple[dict | None, str | None]:
    """Freshest attractive item for the slot + which tier matched, broadening on miss:
    'exact' (theme+merchant) -> 'theme' -> 'merchant' -> 'any'. `pool` is already
    best-first (discount desc). The tier is recorded so a broadened (off-plan) fill is
    visible, not silent.

    `merchant_counts`/`category_counts` (today's fill-so-far tallies, from `_day_mix`,
    keyed via `_norm` — the plan and the deal source don't share a vocabulary) and
    `prev_merchant`/`prev_category` (the immediately-previous post's, matched via the
    looser `_match`) make the pick diversity-aware. A candidate repeating the previous
    post's merchant is used only when every alternative in the tier ALSO repeats it —
    that rule dominates the ranking outright, ahead of the day's counts, so it can
    never be outvoted by a lower running count. Same rule for category. Once that's
    settled, candidates are ranked by least-used merchant, then least-used category,
    then the pool's own best-first order as the final tiebreak — the pool order alone
    never decides a broadened pick. A pool genuinely carrying only the previous
    merchant still fills; no slot is ever dropped for diversity."""
    merchant_counts = merchant_counts or {}
    category_counts = category_counts or {}

    def unused(it):
        return not any(k in used for k in _deal_keys(it))

    def rank(it):
        m, c = _item_merchant(it), it.get("category_key")
        return (1 if m and prev_merchant and _match(m, prev_merchant) else 0,
                1 if c and prev_category and _match(c, prev_category) else 0,
                merchant_counts.get(_norm(m), 0),
                category_counts.get(_norm(c), 0))

    def best(candidates):
        return min(candidates, key=rank) if candidates else None

    exact = [it for it in pool if unused(it) and _match(it.get("category_key"), theme)
            and _match(_item_merchant(it), merchant)]
    if exact:
        return best(exact), "exact"
    by_theme = [it for it in pool if unused(it) and _match(it.get("category_key"), theme)]
    if by_theme:
        return best(by_theme), "theme"
    by_merchant = [it for it in pool if unused(it) and _match(_item_merchant(it), merchant)]
    if by_merchant:
        return best(by_merchant), "merchant"
    any_left = [it for it in pool if unused(it)]
    if any_left:
        return best(any_left), "any"
    return None, None


def _is_loot_type(slot_type: str | None) -> bool:
    return is_loot_type(slot_type)


def _pick_fresh_multi(pool: list[dict], merchant: str | None, used: set[str],
                      n: int) -> list[dict]:
    """Up to `n` freshest unused items spanning DISTINCT categories (one item per
    category, best-first within each) — the actual shape of a real loot post: several
    different product categories bundled together, AND spanning several merchants,
    never one store's whole catalogue. The slot's own `merchant` is still preferred
    first, but capped at `ceil(n * LOOT_MERCHANT_CAP_FRACTION)` items; the rest of the
    board is filled round-robin across the OTHER available merchants (still distinct
    categories), broadening to any merchant/category only if the board is still short."""
    def unused(it):
        return not any(k in used for k in _deal_keys(it))

    seen_cats: set[str] = set()
    picked: list[dict] = []

    def take(it):
        seen_cats.add(it.get("category_key") or "")
        picked.append(it)

    # 1) the slot's own merchant, capped so it can't supply more than ~half the board.
    if merchant:
        cap = min(n, math.ceil(n * LOOT_MERCHANT_CAP_FRACTION))
        for it in pool:
            if len(picked) >= cap:
                break
            cat = it.get("category_key") or ""
            if unused(it) and cat not in seen_cats and _match(_item_merchant(it), merchant):
                take(it)

    # 2) round-robin the OTHER merchants (distinct categories) to fill the rest, so the
    # board spans several stores instead of broadening straight back into the same one.
    if len(picked) < n:
        others: "OrderedDict[str, list[dict]]" = OrderedDict()
        for it in pool:
            cat = it.get("category_key") or ""
            if not unused(it) or cat in seen_cats:
                continue
            if merchant and _match(_item_merchant(it), merchant):
                continue
            others.setdefault(_item_merchant(it) or "?", []).append(it)
        while len(picked) < n and others:
            for mk in list(others):
                if len(picked) >= n:
                    break
                queue = others[mk]
                while queue:
                    it = queue.pop(0)
                    if (it.get("category_key") or "") in seen_cats:
                        continue
                    take(it)
                    break
                if not queue:
                    del others[mk]

    # 3) still short (not enough merchant variety in the pool) -> broaden to ANY
    # merchant/category, including past the slot merchant's cap.
    if len(picked) < n:
        for it in pool:
            if len(picked) >= n:
                break
            if unused(it) and (it.get("category_key") or "") not in seen_cats:
                take(it)

    return picked


def _today_plan(s: Session, day) -> CampaignPlan | None:
    return s.scalar(
        select(CampaignPlan)
        .where(CampaignPlan.plan_type == PlanType.DAILY,
               CampaignPlan.target_date == day,
               CampaignPlan.is_ai_generated == True)  # noqa: E712
        .order_by(CampaignPlan.generated_at.desc())
    )


def _already_filled(s: Session, key: str) -> bool:
    return s.scalar(select(GeneratedPost.id)
                    .where(GeneratedPost.selection_bucket == key).limit(1)) is not None


def _is_due(fire: datetime, now: datetime, horizon: datetime, all_slots: bool,
           backfill_min: int = BACKFILL_MIN) -> bool:
    """G9: due if within the forward lookahead (`now..horizon`), OR — bounded backfill
    — it fired within the last `backfill_min` minutes and was never filled (e.g. the
    app was down). Never reaches further back than that, so it can't spam-post stale
    slots. `all_slots` (offline backfill mode) ignores fire time entirely."""
    if all_slots:
        return True
    if now <= fire <= horizon:
        return True
    return now - timedelta(minutes=backfill_min) <= fire < now


def fill_due_slots(s: Session, lookahead_min: int = LOOKAHEAD_MIN,
                   day=None, all_slots: bool = False, cap_per_type: int | None = None) -> dict:
    from src.services.analytics.periods import ist_today
    from src.ai.client import AIUnavailable
    from src.ai.context import channel_style
    from src.ai.copywriter import Copywriter
    from src.db.org_seed import get_default_org

    settings = get_settings()
    # Where posts are QUEUED to. PUBLISH_CHANNEL (e.g. a test channel) wins over the
    # owned channel, so the agent can keep collecting/learning from the real channel
    # while the posts themselves land somewhere safe. The Publisher enforces the same
    # target again at send time — this only decides what gets queued.
    channels = settings.owned_channels
    channel = settings.publish_channel or (f"@{channels[0].lstrip('@')}" if channels else None)

    # resolve the owned Channel row so filled drafts can carry a baseline prediction
    # (feeds OutcomeCollector -> weekly retro) — best effort, never blocks a fill.
    ch_row = s.scalar(select(Channel).where(
        Channel.kind == "owned", Channel.username == channel.lstrip("@"))) if channel else None
    if ch_row is None:
        ch_row = s.scalars(select(Channel).where(Channel.kind == "owned")).first()
    channel_id = ch_row.id if ch_row else None

    day = day or ist_today()
    plan = _today_plan(s, day)
    if plan is None:
        return {"ok": False, "reason": f"no AI daily plan for {day}"}
    # Cited numbers live only in the plan's rationale, never in the post, so 'warn' is
    # still actionable; only a hard 'failed' (substantial fabrication) blocks filling.
    #
    # DENY-list, not an allow-list. This was `not in ("passed","warn","skipped","")`,
    # which silently blocked every status nobody thought to enumerate — including
    # "fallback", the status the deterministic writer sets when the AI provider is
    # DOWN (controllers/service.py:791). So an AI outage stopped the channel posting
    # entirely, with no error anywhere: the exact failure the fallback writer exists to
    # prevent. Naming only the status that must block means a new status can never
    # take the channel dark by accident.
    if (plan.factcheck_status or "").strip().lower() == "failed":
        return {"ok": False, "reason": f"plan not trusted (factcheck={plan.factcheck_status})"}

    slots = (plan.blueprint or {}).get("post_slots") or []
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(minutes=lookahead_min)
    # Full ordered slot list for the day — the image budget (§8b) is picked against
    # this, not the due-now subset, so which slots get a photo never shifts with when
    # cron happens to run.
    full_slots = _expand_slots(slots, day)
    image_keys = _image_slot_keys(full_slots)
    # all_slots (offline backfill) fills every not-yet-filled slot regardless of fire
    # time; each still enqueues at its real slot time. Normal cron uses the lookahead
    # plus a bounded G9 backfill for recently-missed slots (see _is_due).
    due = [(fire, slot, si, sub) for (fire, slot, si, sub) in full_slots
           if _is_due(fire, now, horizon, all_slots)
           and not _already_filled(s, f"{_SLOT_TAG}:{plan.id}:{si}:{sub}")]
    for fire, slot, si, sub in due:
        if fire < now:
            logger.info("[jit_fill] G9 backfilling missed slot %d:%d (fired %s, %.0fmin ago)",
                        si, sub, fire.isoformat(), (now - fire).total_seconds() / 60)
    # Optional hard cap (test channels): keep at most `cap_per_type` loot + `cap_per_type`
    # deal posts regardless of how many the AI plan produced. Fire-time order preserved.
    if cap_per_type:
        loot = [e for e in due if _is_loot_type(e[1].get("type"))][:cap_per_type]
        deal = [e for e in due if not _is_loot_type(e[1].get("type"))][:cap_per_type]
        due = sorted(loot + deal, key=lambda e: e[0])
    if not due:
        return {"ok": True, "filled": 0, "reason": "no slots due"}

    client = DealSourceClient()
    ok, reason = client.available()
    if not ok:
        return {"ok": False, "reason": reason}
    pool = filter_relevant(client._collect_raw(want=200, page_size=80))
    if not pool:
        return {"ok": False, "reason": "no fresh deals available right now"}

    org = get_default_org(s)
    templates = (org.settings or {}).get("post_templates") if org else None
    style = channel_style(s)
    strategy = PostingStrategy.load(s)
    formatter = PostFormatter(s, affiliate_provider=get_affiliate_provider(org=org),
                              strategy=strategy, templates=templates)
    enricher = DealEnrichmentEngine(s)
    writer = Copywriter()
    used = recently_used_urls(s)
    # fill-time diversity state (AC1/AC2) — read from the DB, not the loop, because
    # jit_fill's own cron ticks are separate process invocations; running tallies below
    # keep it current across multiple due slots filled within THIS tick too.
    mix = _day_mix(s, day)
    merchant_counts = dict(mix["merchant_counts"])
    category_counts = dict(mix["category_counts"])
    prev_merchant = mix["last_merchant"]
    prev_category = mix["last_category"]

    filled = []
    # rotate the post STYLE per single deal and the banner FLAVOUR per loot board, so
    # consecutive posts don't come out looking like the same template.
    single_variant = loot_variant = 0
    # per-run cache of source-filtered price-tier pools, keyed by (floor, cap), so two
    # same-tier loots in one run don't re-hit the export API.
    price_pools: dict[tuple, list[dict]] = {}
    for fire, slot, si, sub in due:
        if _is_loot_type(slot.get("type")):
            # LOOT: several distinct categories bundled under one AI-written banner, each
            # category on its own "<Label> - <link>" line. The AI writes the catch line and
            # labels with <LINK_n> tokens (deterministic template fallback on failure). An
            # optional slot max_price/min_price makes it a price-tier loot ("Under ₹X"
            # or a "₹X-₹Y" band) — fetched straight from the source so the tier is
            # always full and fresh, instead of straining the generic recency pool.
            cap = _as_price(slot.get("max_price"))
            floor = _as_price(slot.get("min_price"))
            if cap or floor:
                pk = (floor, cap)
                if pk not in price_pools:
                    price_pools[pk] = filter_relevant(client._collect_raw(
                        want=200, page_size=80, min_price=floor, max_price=cap))
                # client-side clamp too: the Camoufox fallback can't filter at source.
                loot_pool = [it for it in price_pools[pk] if _in_band(it, floor, cap)]
            else:
                loot_pool = pool
            raws = _pick_fresh_multi(loot_pool, slot.get("merchant"), used, LOOT_ITEMS_PER_POST)
            if len(raws) < 2:
                continue  # not enough qualifying category variety in the live pool right now
            enriched = [e for e in enricher.enrich_batch(
                            [_map_item(r, client.source) for r in raws])
                       if e.deal_validity != "invalid"]
            if len(enriched) < 2:
                continue
            loot_items = []
            for e in enriched:
                lk, _lm = formatter._finalize_link(e)
                loot_items.append({"label": _loot_label(e.category, "Deals"), "link": lk or ""})
            try:
                text = writer.write_for_loot(loot_items, slot, templates, style,
                                             cta=formatter.cta_line,
                                             footer=formatter.footer_line, price_cap=cap,
                                             price_floor=floor, variant=loot_variant)
                if not _loot_copy_matches(text, enriched, price_cap=cap, price_floor=floor):
                    logger.warning(
                        "[jit_fill] slot %d:%d loot AI copy price/discount mismatch vs "
                        "the board's %d real deals — falling back to template",
                        si, sub, len(enriched))
                    raise ValueError("AI loot copy price/discount does not match the real board")
                source = "ai_copywriter"
            except (AIUnavailable, Exception):  # noqa: BLE001 — copy must never block a slot
                text, _ = formatter.format_multi_category_loot(
                    enriched, theme=slot.get("theme"), price_cap=cap, price_floor=floor)
                source = "template_fallback"
            loot_variant += 1
            aff_meta = {"kind": "loot", "items": len(loot_items)}
            match = "multi_category"
            deal_ids = [e.deal_id for e in enriched]
            rank_score = max((e.discount_percent or 0) for e in enriched)
            primary_merchant = enriched[0].merchant_key
            # a loot board spans several categories by design (that's the whole point of
            # `_pick_fresh_multi`'s round-robin) — no single "actually filled" category to
            # tally, so the planned theme is the closest honest label for this post.
            primary_category = slot.get("theme")
            used_urls = [k for r in raws for k in _deal_keys(r)]
            image_candidate = next((e.image for e in enriched if e.image), None)
        else:
            # DEAL: one specific product, AI-written copy (template fallback on failure).
            raw, match = _pick_fresh(pool, slot.get("theme"), slot.get("merchant"), used,
                                     merchant_counts=merchant_counts,
                                     category_counts=category_counts,
                                     prev_merchant=prev_merchant, prev_category=prev_category)
            if raw is None:
                continue
            if match != "exact":
                logger.info("[jit_fill] slot %d:%d broadened (%s): planned theme=%r merchant=%r",
                            si, sub, match, slot.get("theme"), slot.get("merchant"))
            enriched_one = [e for e in enricher.enrich_batch([_map_item(raw, client.source)])
                            if e.deal_validity != "invalid"]
            if not enriched_one:
                continue
            deal = enriched_one[0]
            # Finalize the tracked link before the copywriter runs; it writes a
            # <link/> placeholder that assemble_post swaps for this link.
            link, aff_meta = formatter._finalize_link(deal)
            try:
                text = writer.write_for_item(deal, slot, templates, style, link=link,
                                             footer=formatter.footer_line, variant=single_variant)
                if not _copy_matches_deal(text, deal):
                    logger.warning(
                        "[jit_fill] slot %d:%d AI copy price/discount mismatch vs deal %s "
                        "(price=%s mrp=%s discount=%s%%) — falling back to template",
                        si, sub, deal.deal_id, deal.current_price, deal.original_price,
                        deal.discount_percent)
                    raise ValueError("AI copy price/discount does not match the real deal")
                source = "ai_copywriter"
            except (AIUnavailable, Exception):  # noqa: BLE001 — copy must never block a slot
                text, aff_meta = formatter.format_single(deal)
                source = "template_fallback"
            single_variant += 1
            deal_ids = [deal.deal_id]
            rank_score = deal.discount_percent or 0
            primary_merchant = deal.merchant_key
            # S1-b: the category actually filled (the deal's own category), not the
            # slot's planned theme — a broadened ('merchant'/'any' tier) fill must be
            # tallied under the category it really is, or the tally lies to `rank`.
            primary_category = deal.category
            used_urls = _deal_keys(raw)
            image_candidate = deal.image

        key = f"{_SLOT_TAG}:{plan.id}:{si}:{sub}"
        # §8b image budget: only the ~5 slots picked in image_keys carry a photo, and
        # only if the chosen deal actually had one — every other draft stays text-only.
        image_url = image_candidate if (si, sub) in image_keys else None
        gp = GeneratedPost(
            generated_at=now, post_type=slot.get("type") or "single", selection_bucket=key,
            deal_ids=deal_ids, rendered_text=text,
            format_meta={"source": source, "match": match, "affiliate": aff_meta,
                         "primary_merchant": primary_merchant,
                         "primary_category": primary_category, "image_url": image_url,
                         # S2-b: the slot dict WHOLE — type/time_ist/theme/merchant/
                         # max_price/min_price/why — not just theme+merchant, so a
                         # plan-vs-actual query can be run on every dimension the plan
                         # actually carries, not just the two this file used to keep.
                         "slot": dict(slot)},
            rank_score=rank_score, status=PostStatus.DRAFT,
            strategy_rationale=slot.get("why") or "",
            publish_note="AI-planned slot, filled just-in-time with a fresh deal.")
        s.add(gp)
        s.flush()
        if channel_id is not None:
            try:
                feats, pred = predict_for_slot(s, channel_id, fire, merchant_key=primary_merchant)
                s.add(PostPrediction(
                    generated_post_id=gp.id, model_version=MODEL_VERSION, features=feats,
                    predicted_views_1h=pred["views_1h"], predicted_views_6h=pred["views_6h"],
                    predicted_views_24h=pred["views_24h"],
                    predicted_forwards_24h=pred["forwards_24h"]))
            except Exception:  # noqa: BLE001 — prediction is best-effort, never blocks a fill
                pass
        for u in used_urls:
            if u:
                used.add(u)
        if channel:
            enqueue(s, gp.id, channel, fire)
        # keep the running diversity tallies (AC1/AC2) current for any further due
        # slots this same tick, mirroring what _day_mix would re-derive from the DB —
        # keyed via _norm (S1-b) and against what was ACTUALLY filled, not planned.
        if primary_merchant:
            mk = _norm(primary_merchant)
            merchant_counts[mk] = merchant_counts.get(mk, 0) + 1
            prev_merchant = primary_merchant
        if primary_category:
            ck = _norm(primary_category)
            category_counts[ck] = category_counts.get(ck, 0) + 1
            prev_category = primary_category
        filled.append({"draft_id": gp.id, "slot": f"{si}:{sub}", "source": source,
                       "at_utc": fire.isoformat(), "merchant": primary_merchant,
                       "theme": primary_category})

    # AC4: report the merchant/theme spread of what THIS run filled, so "one merchant
    # took the window" is visible in the run record without a DB query.
    mix_merchant: dict[str, int] = {}
    mix_theme: dict[str, int] = {}
    for f in filled:
        if f.get("merchant"):
            mix_merchant[f["merchant"]] = mix_merchant.get(f["merchant"], 0) + 1
        if f.get("theme"):
            mix_theme[f["theme"]] = mix_theme.get(f["theme"], 0) + 1

    logger.info("[jit_fill] filled %d/%d due slots for %s (mix merchant=%s theme=%s)",
                len(filled), len(due), day, mix_merchant, mix_theme)
    return {"ok": True, "filled": len(filled), "due": len(due), "scheduled": filled,
            "mix": {"merchant": mix_merchant, "theme": mix_theme}}


def _selfcheck() -> None:
    from datetime import date as _date
    slots = [{"window_ist": "09:00-12:00", "count": 3, "type": "single"},
             {"window_ist": "bad", "count": 2},
             {"window_ist": "21:00-23:00", "count": 1}]
    exp = _expand_slots(slots, _date(2026, 7, 13))
    assert len(exp) == 4, exp                       # 3 + skip + 1
    first = [e for e in exp if e[2] == 0]
    gaps = [(first[i + 1][0] - first[i][0]).total_seconds() / 60 for i in range(len(first) - 1)]
    # Spread across the window's FULL 3h span (90min gaps), NOT stacked SPACING_MIN
    # apart at the start — the bug that made a 3h window an 8-minute burst.
    assert gaps == [90.0, 90.0], gaps
    assert gaps[0] > SPACING_MIN, gaps
    # 09:00 IST == 03:30 UTC; the last post lands on the window's end, not near its start
    assert first[0][0].hour == 3 and first[0][0].minute == 30, first[0][0]
    assert first[-1][0].hour == 6 and first[-1][0].minute == 30, first[-1][0]
    # per-post shape: time_ist wins, one post, at exactly that minute (14:05 IST = 08:35 UTC)
    per_post = _expand_slots([{"time_ist": "14:05", "type": "single"}], _date(2026, 7, 13))
    assert len(per_post) == 1, per_post
    assert per_post[0][0].hour == 8 and per_post[0][0].minute == 35, per_post[0][0]
    # a count too large for its span still never collides two posts on one minute
    tight = _slot_fire_times({"window_ist": "09:00-09:03", "count": 9}, _date(2026, 7, 13))
    assert len(set(tight)) == 9, tight
    pool = [{"category_key": "fashion", "merchant_key": "ajio", "original_url": "a"},
            {"category_key": "electronics", "merchant_key": "amazon_in", "original_url": "b"}]
    # vocabulary mismatch must still hit exact: "Electronics"/"Amazon" vs "electronics"/"amazon_in"
    it, tier = _pick_fresh(pool, "Electronics", "Amazon", set())
    assert it["original_url"] == "b" and tier == "exact", (it, tier)
    # theme matches, merchant doesn't -> broadens to 'theme' tier (not straight to 'any')
    it, tier = _pick_fresh(pool, "electronics", "flipkart", set())
    assert it["original_url"] == "b" and tier == "theme", (it, tier)
    # theme misses but merchant matches -> new 'merchant' tier, chosen before 'any'
    it, tier = _pick_fresh(pool, "sports", "amazon", set())
    assert it["original_url"] == "b" and tier == "merchant", (it, tier)
    # neither theme nor merchant match anything in the pool -> 'any'
    it, tier = _pick_fresh(pool, "toys", "swiggy", set())
    assert tier == "any", tier
    it, tier = _pick_fresh(pool, "fashion", "ajio", {"a"})            # only fashion item is used
    assert it["original_url"] == "b" and tier == "any", (it, tier)   # -> broadens past used

    # AC2: within a tier, least-used merchant/category wins over the pool's raw
    # best-first order, and the previous post's merchant is a last resort, not excluded.
    div_pool = [{"category_key": "electronics", "merchant_key": "flipkart", "original_url": "d1"},
               {"category_key": "electronics", "merchant_key": "myntra", "original_url": "d2"}]
    it, tier = _pick_fresh(div_pool, "electronics", None, set(),
                           merchant_counts={"flipkart": 3, "myntra": 0}, category_counts={})
    assert it["original_url"] == "d2" and tier == "theme", (it, tier)  # least-used merchant wins
    it, tier = _pick_fresh(div_pool, "electronics", None, set(),
                           merchant_counts={}, category_counts={}, prev_merchant="myntra")
    assert it["original_url"] == "d1" and tier == "theme", (it, tier)  # avoid repeating prev merchant
    single_pool = [{"category_key": "electronics", "merchant_key": "flipkart", "original_url": "s1"}]
    it, tier = _pick_fresh(single_pool, "electronics", None, set(),
                           merchant_counts={}, category_counts={}, prev_merchant="flipkart")
    assert it["original_url"] == "s1" and tier == "theme", (it, tier)  # sole merchant still fills

    # price-tier band clamp (safety net over the source filter).
    assert _in_band({"discount_price": 400}, None, 500)        # under cap
    assert not _in_band({"discount_price": 600}, None, 500)    # over cap
    assert not _in_band({"discount_price": 0}, None, 500)      # cap needs a real price
    assert _in_band({"discount_price": 700}, 500, 1000)        # inside band
    assert not _in_band({"discount_price": 400}, 500, 1000)    # below floor
    assert _in_band({"discount_price": 5}, None, None)         # no bounds -> always in

    # precision guard: AI copy's ₹/% figures must match the real deal, or fail closed.
    from types import SimpleNamespace
    deal_stub = SimpleNamespace(current_price=873, original_price=9700, discount_percent=91)
    assert _copy_matches_deal("Now only ₹873 (91% off from ₹9,700)", deal_stub)
    assert not _copy_matches_deal("Now only ₹999 (91% off from ₹9,700)", deal_stub)   # wrong price
    assert not _copy_matches_deal("Now only ₹873 (50% off from ₹9,700)", deal_stub)   # wrong discount
    assert _copy_matches_deal("Grab this now, no numbers here", deal_stub)            # nothing to check
    no_price_stub = SimpleNamespace(current_price=None, original_price=None, discount_percent=None)
    assert _copy_matches_deal("₹873 off today!", no_price_stub)  # deal has no known figures -> can't fail

    # coupon guard: a deal's real code must not be overwritten by an invented one.
    coupon_stub = SimpleNamespace(current_price=None, original_price=None, discount_percent=None,
                                  tags=["coupon:SAVE20"])
    assert _copy_matches_deal("Use code SAVE20 at checkout", coupon_stub)
    assert not _copy_matches_deal("Use code FAKE10 at checkout", coupon_stub)  # wrong code
    assert _copy_matches_deal("Grab this deal now", coupon_stub)              # no code mentioned -> fine
    assert _copy_matches_deal("Use code SAVE20", no_price_stub)  # deal has no coupon tag -> can't fail

    # loot sibling: a ₹/% figure only needs to match SOME deal on the board (or the
    # slot's price cap/floor), but a figure-less board fails closed on any ₹/% at all.
    loot_deals = [SimpleNamespace(current_price=299, original_price=999, discount_percent=70),
                 SimpleNamespace(current_price=1499, original_price=None, discount_percent=None)]
    assert _loot_copy_matches("Grab this for just ₹299, or that one at ₹1,499! Up to 70% off", loot_deals)
    assert not _loot_copy_matches("Now at ₹499!", loot_deals)               # no deal has this price
    assert not _loot_copy_matches("Up to 90% off today", loot_deals)        # no deal has this discount
    assert _loot_copy_matches("Under ₹500 today!", loot_deals, price_cap=500)  # cap restated legitimately
    assert not _loot_copy_matches("Under ₹700 today!", loot_deals, price_cap=500)  # invented cap figure
    figureless = [SimpleNamespace(current_price=None, original_price=None, discount_percent=None)]
    assert not _loot_copy_matches("Grab it for ₹299!", figureless)  # nothing on the board to verify against
    assert _loot_copy_matches("Grab this deal, no numbers here", figureless)  # nothing to check at all

    # FIX 6: a loot board must span merchants — the slot's own merchant is capped at
    # ceil(n/2), the rest filled round-robin across other available merchants.
    loot_pool = (
        [{"category_key": f"amazon_cat{i}", "merchant_key": "amazon", "original_url": f"a{i}"}
         for i in range(8)]
        + [{"category_key": f"flipkart_cat{i}", "merchant_key": "flipkart", "original_url": f"f{i}"}
           for i in range(3)]
        + [{"category_key": f"myntra_cat{i}", "merchant_key": "myntra", "original_url": f"m{i}"}
           for i in range(2)]
    )
    board = _pick_fresh_multi(loot_pool, "amazon", set(), 10)
    assert len(board) == 10, board
    counts = {}
    for it in board:
        counts[it["merchant_key"]] = counts.get(it["merchant_key"], 0) + 1
    assert counts.get("amazon", 0) <= 5, counts        # <= ceil(10/2), other merchants available
    assert counts.get("flipkart", 0) >= 1 and counts.get("myntra", 0) >= 1, counts  # board spans stores

    # §8b: ~5 evenly-spaced image slots; short days give every slot an image.
    idx24 = _image_slot_indices(24)
    assert len(idx24) == 5 and idx24 == {4, 8, 12, 16, 20}, idx24
    assert _image_slot_indices(3) == {0, 1, 2}                        # fewer than k -> all
    assert _image_slot_indices(5) == {0, 1, 2, 3, 4}                  # exactly k -> all

    # G9: backfill fires within the last BACKFILL_MIN once, never further back, never
    # ahead of the normal lookahead horizon.
    t0 = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    horizon = t0 + timedelta(minutes=LOOKAHEAD_MIN)
    assert _is_due(t0 + timedelta(minutes=1), t0, horizon, False)              # forward window
    assert _is_due(t0 - timedelta(minutes=10), t0, horizon, False)             # recently missed
    assert not _is_due(t0 - timedelta(minutes=BACKFILL_MIN + 1), t0, horizon, False)  # too old
    assert _is_due(t0 - timedelta(minutes=BACKFILL_MIN * 2), t0, horizon, True)       # all_slots override
    print("jit_fill selfcheck ok")


if __name__ == "__main__":
    _selfcheck()
