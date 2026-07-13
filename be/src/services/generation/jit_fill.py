"""Just-in-time slot fill — the fresh-posting executor.

The AI daily plan (CampaignPlan.blueprint["post_slots"]) decides strategy: for each
post, a time window, a type (single/collection), a theme (category) and a merchant.
This worker fills those slots with FRESH inventory ~3 minutes before each fires:

  every minute → find slots due within the lookahead → scrape today's live pool →
  pick a fresh item matching the slot's theme/merchant → AI-write the post from the
  matching deal/loot template → queue it at the slot time.

Freshness + "delayed retries" are structural: the job runs every minute with a
3-minute lookahead, so an unfilled slot is retried ~3 times before it fires (a
scrape that fails this minute is re-attempted next minute). Idempotency: a filled
slot leaves a GeneratedPost tagged with the slot key, so it is never filled twice.

Per-slot fallback (never post stale/nothing when avoidable): if the exact merchant
is dry, broaden to any fresh item of the slot's theme, then any fresh item at all;
if the AI copywriter is unavailable, render the deterministic template instead.
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.services.affiliate import get_affiliate_provider
from src.services.automation.queue import IST, enqueue
from src.services.collection.deal_scraper import filter_relevant
from src.services.generation.deal_source import DealSourceClient, _map_item
from src.services.generation.enrichment import DealEnrichmentEngine
from src.services.generation.formatting import PostFormatter
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
SPACING_MIN = 2        # gap between consecutive posts sharing one window
_SLOT_TAG = "aislot"   # GeneratedPost.selection_bucket prefix marking a filled slot

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


def fill_due_slots(s: Session, lookahead_min: int = LOOKAHEAD_MIN) -> dict:
    from src.services.analytics.periods import ist_today
    from src.ai.client import AIUnavailable
    from src.ai.context import channel_style
    from src.ai.copywriter import Copywriter
    from src.db.org_seed import get_default_org

    settings = get_settings()
    channels = settings.owned_channels
    channel = f"@{channels[0].lstrip('@')}" if channels else None

    # resolve the owned Channel row so filled drafts can carry a baseline prediction
    # (feeds OutcomeCollector -> weekly retro) — best effort, never blocks a fill.
    ch_row = s.scalar(select(Channel).where(
        Channel.kind == "owned", Channel.username == channel.lstrip("@"))) if channel else None
    if ch_row is None:
        ch_row = s.scalars(select(Channel).where(Channel.kind == "owned")).first()
    channel_id = ch_row.id if ch_row else None

    day = ist_today()
    plan = _today_plan(s, day)
    if plan is None:
        return {"ok": False, "reason": "no AI daily plan for today"}
    if (plan.factcheck_status or "") not in ("passed", "skipped", ""):
        return {"ok": False, "reason": f"plan not trusted (factcheck={plan.factcheck_status})"}

    slots = (plan.blueprint or {}).get("post_slots") or []
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(minutes=lookahead_min)
    due = [(fire, slot, si, sub) for (fire, slot, si, sub) in _expand_slots(slots, day)
           if now <= fire <= horizon and not _already_filled(s, f"{_SLOT_TAG}:{plan.id}:{si}:{sub}")]
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
    for fire, slot, si, sub in due:
        raw, match = _pick_fresh(pool, slot.get("theme"), slot.get("merchant"), used)
        if raw is None:
            continue
        if match != "exact":
            logger.info("[jit_fill] slot %d:%d broadened (%s): planned theme=%r merchant=%r",
                        si, sub, match, slot.get("theme"), slot.get("merchant"))
        enriched = [e for e in enricher.enrich_batch([_map_item(raw, client.source)])
                    if e.deal_validity != "invalid"]
        if not enriched:
            continue
        deal = enriched[0]
        try:
            text = writer.write_for_item(deal, slot, templates, style)
            source = "ai_copywriter"
        except (AIUnavailable, Exception):  # noqa: BLE001 — copy must never block a slot
            text, _ = formatter.format_single(deal)
            source = "template_fallback"
        key = f"{_SLOT_TAG}:{plan.id}:{si}:{sub}"
        gp = GeneratedPost(
            generated_at=now, post_type=slot.get("type") or "single", selection_bucket=key,
            deal_ids=[deal.deal_id], rendered_text=text,
            format_meta={"source": source, "match": match,
                         "slot": {"theme": slot.get("theme"), "merchant": slot.get("merchant")}},
            rank_score=deal.discount_percent or 0, status=PostStatus.DRAFT,
            strategy_rationale=slot.get("why") or "",
            publish_note="AI-planned slot, filled just-in-time with a fresh deal.")
        s.add(gp)
        s.flush()
        if channel_id is not None:
            try:
                feats, pred = predict_for_slot(s, channel_id, fire, merchant_key=deal.merchant_key)
                s.add(PostPrediction(
                    generated_post_id=gp.id, model_version=MODEL_VERSION, features=feats,
                    predicted_views_1h=pred["views_1h"], predicted_views_6h=pred["views_6h"],
                    predicted_views_24h=pred["views_24h"],
                    predicted_forwards_24h=pred["forwards_24h"]))
            except Exception:  # noqa: BLE001 — prediction is best-effort, never blocks a fill
                pass
        used.add(raw.get("original_url"))
        if channel:
            enqueue(s, gp.id, channel, fire)
        filled.append({"draft_id": gp.id, "slot": f"{si}:{sub}", "source": source,
                       "at_utc": fire.isoformat(), "merchant": deal.merchant_key})

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
    print("jit_fill selfcheck ok")


if __name__ == "__main__":
    _selfcheck()
