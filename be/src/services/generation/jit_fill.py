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

import re
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

_HHMM = re.compile(r"(\d{1,2}):(\d{2})")


def _window_start(window_ist: str) -> time | None:
    m = _HHMM.search(window_ist or "")
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    return time(hh % 24, mm % 60) if hh < 24 else None


def _expand_slots(post_slots: list[dict], base_day) -> list[tuple[datetime, dict, int, int]]:
    """Each slot -> one entry per post (count), spaced SPACING_MIN apart from the
    window start. Returns (fire_utc, slot, slot_index, sub_index), skipping slots
    with an unparseable window. Pure — unit-tested in _selfcheck."""
    out: list[tuple[datetime, dict, int, int]] = []
    for si, slot in enumerate(post_slots or []):
        start = _window_start(slot.get("window_ist", ""))
        if start is None:
            continue
        base = datetime.combine(base_day, start, tzinfo=IST)
        for sub in range(max(1, int(slot.get("count") or 1))):
            fire = (base + timedelta(minutes=SPACING_MIN * sub)).astimezone(timezone.utc)
            out.append((fire, slot, si, sub))
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
    just due-now) — chosen as the day's ~5 image posts."""
    idx = _image_slot_indices(len(full_slots))
    return {(full_slots[i][2], full_slots[i][3]) for i in idx}


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


def _pick_fresh(pool: list[dict], theme: str | None, merchant: str | None,
                used: set[str]) -> tuple[dict | None, str | None]:
    """Freshest attractive item for the slot + which tier matched, broadening on miss:
    'exact' (theme+merchant) -> 'theme' -> 'any'. `pool` is already best-first.
    The tier is recorded so a broadened (off-plan) fill is visible, not silent."""
    def unused(it):
        return it.get("original_url") not in used

    for it in pool:
        if unused(it) and _match(it.get("category_key"), theme) and _match(_item_merchant(it), merchant):
            return it, "exact"
    for it in pool:
        if unused(it) and _match(it.get("category_key"), theme):
            return it, "theme"
    for it in pool:
        if unused(it):
            return it, "any"
    return None, None


def _is_loot_type(slot_type: str | None) -> bool:
    return is_loot_type(slot_type)


def _pick_fresh_multi(pool: list[dict], merchant: str | None, used: set[str],
                      n: int) -> list[dict]:
    """Up to `n` freshest unused items spanning DISTINCT categories (one item per
    category, best-first within each) — the actual shape of a real loot post: several
    different product categories bundled together, never several products of the
    SAME category. Prefers `merchant` when given but broadens to any merchant once
    that one's categories are exhausted, since a loot post's defining trait is
    category variety, not a single merchant."""
    def unused(it):
        return it.get("original_url") not in used

    seen_cats: set[str] = set()
    picked: list[dict] = []

    def _scan(require_merchant: bool):
        for it in pool:
            if len(picked) >= n:
                return
            if not unused(it):
                continue
            cat = it.get("category_key") or ""
            if cat in seen_cats:
                continue
            if require_merchant and not _match(_item_merchant(it), merchant):
                continue
            seen_cats.add(cat)
            picked.append(it)

    if merchant:
        _scan(require_merchant=True)
    _scan(require_merchant=False)
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
    if (plan.factcheck_status or "") not in ("passed", "warn", "skipped", ""):
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

    filled = []
    # rotate the post STYLE per single deal and the banner FLAVOUR per loot board, so
    # consecutive posts don't come out looking like the same template.
    single_variant = loot_variant = 0
    for fire, slot, si, sub in due:
        if _is_loot_type(slot.get("type")):
            # LOOT: several distinct categories bundled under one AI-written banner, each
            # category on its own "<Label> - <link>" line. The AI writes the catch line and
            # labels with <LINK_n> tokens (deterministic template fallback on failure). An
            # optional slot max_price makes it a price-tier loot ("Under ₹X").
            cap = _as_price(slot.get("max_price"))
            loot_pool = ([it for it in pool if (_item_price(it) or 0) <= cap and _item_price(it)]
                         if cap else pool)
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
                                             variant=loot_variant)
                source = "ai_copywriter"
            except (AIUnavailable, Exception):  # noqa: BLE001 — copy must never block a slot
                text, _ = formatter.format_multi_category_loot(
                    enriched, theme=slot.get("theme"), price_cap=cap)
                source = "template_fallback"
            loot_variant += 1
            aff_meta = {"kind": "loot", "items": len(loot_items)}
            match = "multi_category"
            deal_ids = [e.deal_id for e in enriched]
            rank_score = max((e.discount_percent or 0) for e in enriched)
            primary_merchant = enriched[0].merchant_key
            used_urls = [r.get("original_url") for r in raws]
            image_candidate = next((e.image for e in enriched if e.image), None)
        else:
            # DEAL: one specific product, AI-written copy (template fallback on failure).
            raw, match = _pick_fresh(pool, slot.get("theme"), slot.get("merchant"), used)
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
                source = "ai_copywriter"
            except (AIUnavailable, Exception):  # noqa: BLE001 — copy must never block a slot
                text, aff_meta = formatter.format_single(deal)
                source = "template_fallback"
            single_variant += 1
            deal_ids = [deal.deal_id]
            rank_score = deal.discount_percent or 0
            primary_merchant = deal.merchant_key
            used_urls = [raw.get("original_url")]
            image_candidate = deal.image

        key = f"{_SLOT_TAG}:{plan.id}:{si}:{sub}"
        # §8b image budget: only the ~5 slots picked in image_keys carry a photo, and
        # only if the chosen deal actually had one — every other draft stays text-only.
        image_url = image_candidate if (si, sub) in image_keys else None
        gp = GeneratedPost(
            generated_at=now, post_type=slot.get("type") or "single", selection_bucket=key,
            deal_ids=deal_ids, rendered_text=text,
            format_meta={"source": source, "match": match, "affiliate": aff_meta,
                         "primary_merchant": primary_merchant, "image_url": image_url,
                         "slot": {"theme": slot.get("theme"), "merchant": slot.get("merchant")}},
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
        filled.append({"draft_id": gp.id, "slot": f"{si}:{sub}", "source": source,
                       "at_utc": fire.isoformat(), "merchant": primary_merchant})

    logger.info("[jit_fill] filled %d/%d due slots for %s", len(filled), len(due), day)
    return {"ok": True, "filled": len(filled), "due": len(due), "scheduled": filled}


def _selfcheck() -> None:
    from datetime import date as _date
    slots = [{"window_ist": "09:00-12:00", "count": 3, "type": "single"},
             {"window_ist": "bad", "count": 2},
             {"window_ist": "21:00-23:00", "count": 1}]
    exp = _expand_slots(slots, _date(2026, 7, 13))
    assert len(exp) == 4, exp                       # 3 + skip + 1
    first = [e for e in exp if e[2] == 0]
    gaps = [(first[i + 1][0] - first[i][0]).total_seconds() / 60 for i in range(len(first) - 1)]
    assert gaps == [SPACING_MIN, SPACING_MIN], gaps  # spaced 2 min apart
    # 09:00 IST == 03:30 UTC
    assert first[0][0].hour == 3 and first[0][0].minute == 30, first[0][0]
    pool = [{"category_key": "fashion", "merchant_key": "ajio", "original_url": "a"},
            {"category_key": "electronics", "merchant_key": "amazon_in", "original_url": "b"}]
    # vocabulary mismatch must still hit exact: "Electronics"/"Amazon" vs "electronics"/"amazon_in"
    it, tier = _pick_fresh(pool, "Electronics", "Amazon", set())
    assert it["original_url"] == "b" and tier == "exact", (it, tier)
    it, tier = _pick_fresh(pool, "electronics", "flipkart", set())
    assert it["original_url"] == "b" and tier == "theme", (it, tier)   # merchant broaden -> tier tagged
    it, tier = _pick_fresh(pool, "toys", None, set())
    assert tier == "any", tier                                        # theme broaden -> tier tagged
    it, tier = _pick_fresh(pool, "fashion", "ajio", {"a"})            # only fashion item is used
    assert it["original_url"] == "b" and tier == "any", (it, tier)   # -> broadens past used

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
