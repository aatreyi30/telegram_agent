"""Daily category plan — schedule each category's fresh deals at its best time.

Builds a full day of posts:
  1. best posting times come from your OWNED view data (which IST hours get the most
     views) — real, not guessed.
  2. each time-slot is assigned a CATEGORY — your preferred categories first, then the
     categories with the strongest available deals (deal_score), covering ALL categories.
  3. for each slot we take that category's freshest, most attractive deals, DEDUPED
     against deals used in recent drafts (no more repeats), draft a collection, and queue
     it at the slot time. The queue processor publishes it when the time arrives.

Honest note: per-category *owned* view history isn't available (owned posts aren't
category-labelled), so category priority uses live deal quality + your preference, while
timing uses real owned view peaks.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.services.affiliate import get_affiliate_provider
from src.services.automation.queue import IST, enqueue
from src.services.collection.deal_scraper import filter_relevant
from src.services.generation.deal_source import DealSourceClient, _map_item
from src.services.generation.enrichment import DealEnrichmentEngine
from src.services.generation.formatting import PostFormatter
from src.services.generation.strategy import PostingStrategy
from src.config.settings import get_settings
from src.db.models import Channel
from src.db.models_generation import EnrichedDeal, GeneratedPost, PostStatus
from src.db.models_prediction import PostPrediction
from src.services.analytics.prediction import MODEL_VERSION, dominant_merchant_key, predict_for_slot
from src.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_HOURS = [9, 12, 15, 18, 21]


def recently_used_urls(s: Session, days: int = 3) -> set[str]:
    """Product URLs already used in drafts in the last `days` — so we never repeat."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deal_ids: set[str] = set()
    for gp in s.scalars(select(GeneratedPost).where(GeneratedPost.generated_at >= cutoff)):
        for d in (gp.deal_ids or []):
            deal_ids.add(d)
    if not deal_ids:
        return set()
    urls: set[str] = set()
    for e in s.scalars(select(EnrichedDeal).where(EnrichedDeal.deal_id.in_(deal_ids))):
        if e.url:
            urls.add(e.url)
        if e.clean_url:
            urls.add(e.clean_url)
    return urls


def _best_hours(s: Session, max_slots: int) -> list[int]:
    """The PROVEN best posting hours (IST) — the same signal as the learning
    'strongest proven posting windows' statement: age-normalized views/day,
    sample-gated (n>=100). This avoids the cumulative-view bias in raw avg-views,
    which wrongly favoured tiny-sample late-night hours (00:00/04:00/05:00)."""
    from src.db.models_learning import LEARNING_VERSION, LearningRecord

    rec = s.scalar(select(LearningRecord).where(
        LearningRecord.learning_version == LEARNING_VERSION,
        LearningRecord.category == "timing"))
    hours: list[int] = []
    if rec and rec.evidence:
        # reliable_windows: [[hour, views_per_day, n, lift], ...] already best-first
        hours = [int(w[0]) for w in (rec.evidence.get("reliable_windows") or [])]
        if len(hours) < max_slots:
            # pad with the next-best hours that still clear a softer sample gate (n>=50),
            # never the tiny-sample noise the learning flags as "experiments"
            hourly = rec.evidence.get("hourly_all") or []  # [[hour, views_per_day, n], ...]
            extra = sorted((h for h in hourly if (h[2] or 0) >= 50 and int(h[0]) not in hours),
                           key=lambda h: h[1], reverse=True)
            hours += [int(h[0]) for h in extra]
    if not hours:  # no learning yet → fall back to sample-gated raw hours
        from src.services.analytics import views as vv
        a = vv.compute(s)
        ranked = sorted((h for h in a.get("by_hour", []) if h.get("n", 0) >= 50),
                        key=lambda x: x.get("avg_views", 0), reverse=True)
        hours = [int(h["label"][:2]) for h in ranked]
    hours = hours[:max_slots] or _DEFAULT_HOURS
    return sorted(set(hours))


def _next_occurrence(hour: int, now_ist: datetime) -> datetime:
    slot = now_ist.replace(hour=hour, minute=0, second=0, microsecond=0)
    if slot <= now_ist:
        slot += timedelta(days=1)
    return slot.astimezone(timezone.utc)


def build_and_schedule_day(s: Session, max_slots: int = 8, per_collection: int = 4) -> dict:
    settings = get_settings()
    from src.db.org_seed import get_default_org
    org = get_default_org(s)
    preferred = list((org.settings or {}).get("preferred_categories") or []) if org else []
    channels = settings.owned_channels
    channel = f"@{channels[0].lstrip('@')}" if channels else None

    # resolve the owned Channel row (int FK) so queued drafts can carry a
    # Phase 2.2 baseline_v1 prediction -- best effort, never blocks planning.
    channel_row = None
    if channel:
        channel_row = s.scalar(
            select(Channel).where(Channel.kind == "owned", Channel.username == channel.lstrip("@"))
        )
    if channel_row is None:
        channel_row = s.scalars(select(Channel).where(Channel.kind == "owned")).first()
    channel_id = channel_row.id if channel_row else None

    # idempotent day: clear prior AUTO-PLANNED queued drafts so re-running rebuilds
    # a fresh day rather than stacking duplicate slots (manual drafts are untouched).
    from src.db.models_automation import ScheduleStatus, ScheduledPost
    prior = [gp.id for gp in s.scalars(
        select(GeneratedPost).where(GeneratedPost.status == PostStatus.DRAFT,
                                    GeneratedPost.publish_note.like("Auto-planned%")))]
    if prior:
        s.query(ScheduledPost).filter(
            ScheduledPost.generated_post_id.in_(prior),
            ScheduledPost.status.in_([ScheduleStatus.QUEUED, ScheduleStatus.RETRY])
        ).delete(synchronize_session=False)
        s.query(GeneratedPost).filter(GeneratedPost.id.in_(prior)).delete(synchronize_session=False)
        s.flush()

    client = DealSourceClient()
    ok, reason = client.available()
    if not ok:
        return {"ok": False, "reason": reason}

    raw = client._collect_raw(want=max(max_slots * 60, 400), page_size=80)
    relevant = filter_relevant(raw)
    if not relevant:
        return {"ok": False, "reason": "no relevant deals available right now"}

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for it in relevant:                       # relevant is already most-attractive first
        by_cat[it.get("category_key") or "other"].append(it)

    # category order: preferred (that exist) first, then strongest available deals
    def cat_strength(c: str) -> float:
        return max((x.get("deal_score") or 0) for x in by_cat[c])
    cats = [c for c in preferred if c in by_cat] + \
           sorted((c for c in by_cat if c not in preferred), key=cat_strength, reverse=True)
    if not cats:
        return {"ok": False, "reason": "no categories with deals"}

    hours = _best_hours(s, max_slots)
    # one category per slot; cover all categories, cycling if more slots than categories
    assignments = [(hours[i], cats[i % len(cats)]) for i in range(len(hours))]

    used = recently_used_urls(s)
    strategy = PostingStrategy.load(s)
    formatter = PostFormatter(s, affiliate_provider=get_affiliate_provider(org=org), strategy=strategy)
    enricher = DealEnrichmentEngine(s)
    now_ist = datetime.now(timezone.utc).astimezone(IST)
    now = datetime.now(timezone.utc)

    scheduled = []
    for hour, cat in assignments:
        fresh = [it for it in by_cat[cat] if it.get("original_url") not in used][:per_collection]
        if len(fresh) < 2:
            continue                          # need >=2 for a collection; skip thin categories
        enriched = [e for e in enricher.enrich_batch([_map_item(it, "grabcash_api") for it in fresh])
                    if e.deal_validity != "invalid"]
        if len(enriched) < 2:
            continue
        text, meta = formatter.format_category_collection(cat, enriched[:per_collection])
        gp = GeneratedPost(
            generated_at=now, post_type="category_collection", selection_bucket=cat,
            deal_ids=[e.deal_id for e in enriched], rendered_text=text, format_meta=meta,
            rank_score=max((e.discount_percent or 0) for e in enriched), status=PostStatus.DRAFT,
            strategy_rationale=strategy.rationale(
                "collection", note=f"{cat} scheduled at {hour:02d}:00 IST (a peak-views hour)"),
            publish_note="Auto-planned draft (category × best-time). Review before publishing.")
        s.add(gp)
        s.flush()
        when = _next_occurrence(hour, now_ist)
        if channel_id is not None:
            # Phase 2.2 -- baseline_v1 prediction for this draft, written now
            # (post_type_cluster is unknown pre-send; see predict_for_slot's
            # docstring) so the OutcomeCollector has something to score against.
            merchant_key = dominant_merchant_key(enriched)
            features, prediction = predict_for_slot(s, channel_id, when, merchant_key=merchant_key)
            s.add(PostPrediction(
                generated_post_id=gp.id,
                predicted_views_1h=prediction["views_1h"],
                predicted_views_6h=prediction["views_6h"],
                predicted_views_24h=prediction["views_24h"],
                predicted_forwards_24h=prediction["forwards_24h"],
                model_version=MODEL_VERSION,
                features=features,
            ))
        if channel:
            enqueue(s, gp.id, channel, when)
        used |= {it.get("original_url") for it in fresh}
        scheduled.append({"draft_id": gp.id, "category": cat, "hour_ist": hour,
                          "at_utc": when.isoformat(), "deals": len(enriched)})

    logger.info("[daily_planner] scheduled %d category posts across %d slots",
                len(scheduled), len(assignments))
    return {"ok": True, "slots": len(assignments),
            "categories": sorted({c for _, c in assignments}),
            "scheduled": scheduled, "deduped_against": len(used)}
