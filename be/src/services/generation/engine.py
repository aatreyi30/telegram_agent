"""Post Generation Engine orchestrator (source_truth/04 Phase 9).

Ties the four responsibilities together:
  enrich (Deal Enrichment Engine) -> rank -> select (diversity) -> format -> draft.

Produces GeneratedPost DRAFTS only. Publishing is a separate, gated step
(generation never auto-publishes).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from src.services.affiliate import get_affiliate_provider
from src.services.collection.base import BaseCollector, CollectorResult
from src.services.generation.strategy import PostingStrategy
from src.db.models_generation import EnrichedDeal, GeneratedPost, PostStatus
from src.db.models_learning import LEARNING_VERSION, PostTypePerformance
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus
from src.services.generation.candidates import observed_candidates
from src.services.generation.enrichment import DealEnrichmentEngine, RawDeal
from src.services.generation.formatting import PostFormatter
from src.services.generation.ranking import DealRanker, DealSelector, StrategyAwareSelector
from src.logger import get_logger

logger = get_logger(__name__)


def _default_org(s):
    """The org that owns generation (for per-org affiliate provider). None-safe."""
    try:
        from src.db.org_seed import get_default_org
        return get_default_org(s)
    except Exception:  # org table absent / not seeded -> fall back to .env provider
        return None


class PostGenerationEngine(BaseCollector):
    name = "post_generation"
    retryable = False

    def __init__(self, raw_deals: list[dict], count: int = 5, make_collection: bool = True):
        self.raw = [RawDeal.from_dict(d) for d in raw_deals]
        self.count = count
        self.make_collection = make_collection
        self.bus = get_event_bus()

    def run(self, job) -> CollectorResult:
        result = CollectorResult()
        now = datetime.now(timezone.utc)
        if not self.raw:
            result.skipped_reason = "No raw deals supplied."
            return result

        with session_scope() as s:
            # 1) ENRICH
            enriched = DealEnrichmentEngine(s).enrich_batch(self.raw)
            result.processed = len(enriched)
            for d in enriched:
                self.bus.publish(Event(event_type=EventType.DEAL_ENRICHED, entity_type="deal",
                                       entity_id=d.deal_id, data={"merchant": d.merchant_key},
                                       job_id=job.id))
            # 2) RANK  3) SELECT (strategy-aware: caps low-price singles)
            org = _default_org(s)
            strategy = PostingStrategy.load(s)
            ranked = DealRanker(s).rank(enriched)
            selected = StrategyAwareSelector(strategy).select(ranked, count=self.count)
            # 4) FORMAT -> draft GeneratedPosts (affiliate links + emoji policy enforced)
            templates = (org.settings or {}).get("post_templates") if org else None
            formatter = PostFormatter(s, affiliate_provider=get_affiliate_provider(org=org),
                                      strategy=strategy, templates=templates)
            created = 0

            for deal, bucket in selected:
                text, meta = formatter.format_single(deal)
                s.add(GeneratedPost(
                    generated_at=now, post_type="single", selection_bucket=bucket,
                    deal_ids=[deal.deal_id], rendered_text=text, format_meta=meta,
                    rank_score=deal.rank_score, status=PostStatus.DRAFT,
                    strategy_rationale=strategy.rationale("single", deal=deal),
                    publish_note="Draft — review before publishing.",
                ))
                created += 1

            if self.make_collection and len(selected) >= 2:
                deals = [d for d, _ in selected]
                # No explicit theme -> falls back to the org's editable
                # collection_theme_default template (Settings > Post Templates).
                text, meta = formatter.format_collection(deals)
                s.add(GeneratedPost(
                    generated_at=now, post_type="collection", selection_bucket="collection",
                    deal_ids=[d.deal_id for d in deals], rendered_text=text, format_meta=meta,
                    rank_score=(sum(d.rank_score or 0 for d in deals) / len(deals)),
                    status=PostStatus.DRAFT,
                    strategy_rationale=strategy.rationale("collection", deals=deals),
                    publish_note="Draft collection — review before publishing.",
                ))
                created += 1

            result.added = created

        self.bus.publish(Event(event_type=EventType.POST_GENERATED, entity_type="channel",
                               entity_id="owned", data={"drafts": result.added}, job_id=job.id))
        logger.info("[post_generation] enriched %d, selected %d, drafted %d posts",
                    result.processed, len(selected), result.added)
        return result


class LiveDealGenerationEngine(BaseCollector):
    """Generate drafts from TODAY's fetched deals (source_truth/06 flow).

    Groups fresh enriched deals by their real category into the channel's
    signature '<Category> Under ₹X' collections, plus standout single deals.
    Uses the real product URLs the source provides. Never auto-publishes.
    """

    name = "generate_live"
    retryable = False

    def __init__(self, raw_deals: list[dict], count: int = 5, per_collection: int = 4):
        self.raw = [RawDeal.from_dict(d) for d in raw_deals]
        self.count = count
        self.per_collection = per_collection
        self.bus = get_event_bus()

    def run(self, job) -> CollectorResult:
        result = CollectorResult()
        now = datetime.now(timezone.utc)
        if not self.raw:
            result.skipped_reason = "No deals fetched."
            return result

        with session_scope() as s:
            enriched = DealEnrichmentEngine(s).enrich_batch(self.raw)
            result.processed = len(enriched)
            # group by real category (skip unknown), best-discounted first within each
            groups: dict[str, list[EnrichedDeal]] = {}
            for d in enriched:
                if d.deal_validity == "invalid":
                    continue
                cat = d.category if d.category and d.category != "unknown" else None
                groups.setdefault(cat or "_ungrouped", []).append(d)
            for cat in groups:
                groups[cat].sort(key=lambda d: (d.discount_percent or 0), reverse=True)

            # rank categories by best-deal depth; take the top `count` distinct categories
            ranked_cats = sorted(
                (c for c in groups if c != "_ungrouped"),
                key=lambda c: max((d.discount_percent or 0) for d in groups[c]), reverse=True,
            )
            org = _default_org(s)
            strategy = PostingStrategy.load(s)
            templates = (org.settings or {}).get("post_templates") if org else None
            formatter = PostFormatter(s, affiliate_provider=get_affiliate_provider(org=org),
                                      strategy=strategy, templates=templates)
            # Strategy: multi-link collections are the winning type -> prefer them; cap
            # single-deal posts (a below-average type) at ~20% of the batch.
            single_cap = max(1, self.count // 5)
            created, singles = 0, 0
            for cat in ranked_cats:
                if created >= self.count:
                    break
                deals = groups[cat][: self.per_collection]
                if len(deals) >= 2:
                    text, meta = formatter.format_category_collection(cat, deals)
                    ptype, rationale = "category_collection", strategy.rationale(
                        "collection", note=f"Category: {cat}", deals=deals)
                else:
                    if singles >= single_cap:
                        continue  # honor the strategy cap on single-deal posts
                    text, meta = formatter.format_single(deals[0])
                    ptype, rationale = "single", strategy.rationale(
                        "single", note=f"Category: {cat}", deal=deals[0])
                    singles += 1
                s.add(GeneratedPost(
                    generated_at=now, post_type=ptype, selection_bucket=cat,
                    deal_ids=[d.deal_id for d in deals], rendered_text=text, format_meta=meta,
                    rank_score=max((d.discount_percent or 0) for d in deals),
                    status=PostStatus.DRAFT, strategy_rationale=rationale,
                    publish_note="Draft from TODAY's live deals (real links). Review before publishing.",
                ))
                created += 1
            result.added = created

        self.bus.publish(Event(event_type=EventType.POST_GENERATED, entity_type="channel",
                               entity_id="owned", data={"drafts": result.added, "source": "live"},
                               job_id=job.id))
        logger.info("[generate_live] enriched %d fresh deals -> %d category drafts",
                    result.processed, result.added)
        return result


class ObservedPostGenerationEngine(BaseCollector):
    """Generate drafts from REAL observed deals (real, reachable grbn.in links).

    Loot/multi-link posts are rendered as themed collections exactly like the
    channel posts them. Ranked by the learned performance of each post type
    (Phase 6), selected for theme variety. No URLs are fabricated.
    """

    name = "post_generation_observed"
    retryable = False

    def __init__(self, limit: int = 20, count: int = 5, window_days: int = 120):
        self.limit = limit
        self.count = count
        self.window_days = window_days
        self.bus = get_event_bus()

    def run(self, job) -> CollectorResult:
        result = CollectorResult()
        now = datetime.now(timezone.utc)
        with session_scope() as s:
            cands = observed_candidates(s, limit=self.limit, window_days=self.window_days)
            perf = {p.post_type: (p.avg_views_per_day or 0.0) for p in s.scalars(
                select(PostTypePerformance).where(
                    PostTypePerformance.learning_version == LEARNING_VERSION))}
            result.processed = len(cands)
            if not cands:
                result.skipped_reason = "No observed deal candidates with links found."
                return result

            # rank by learned performance of the candidate's post type
            cands.sort(key=lambda c: perf.get(c.cluster or "", 0.0), reverse=True)
            # select for theme variety (avoid repeating the same theme)
            selected, seen_themes = [], set()
            for c in cands:
                key = (c.theme or "").lower()[:24]
                if key in seen_themes:
                    continue
                seen_themes.add(key)
                selected.append(c)
                if len(selected) >= self.count:
                    break

            org = _default_org(s)
            strategy = PostingStrategy.load(s)
            templates = (org.settings or {}).get("post_templates") if org else None
            formatter = PostFormatter(s, affiliate_provider=get_affiliate_provider(org=org),
                                      strategy=strategy, templates=templates)
            created = 0
            for c in selected:
                type_vpd = perf.get(c.cluster or "", 0.0)
                cand_note = (f"This theme's post type averages ~{type_vpd:.0f} views/day historically — "
                             "ranked above other observed-deal candidates on that basis."
                             if type_vpd else None)
                if c.kind == "collection":
                    text, meta = formatter.format_observed_collection(c)
                    ptype, rk = "loot_collection", strategy.rationale("collection", note=cand_note)
                else:
                    text, meta = formatter.format_observed_single(c)
                    ptype, rk = "single", strategy.rationale("single", note=cand_note)
                meta["source_post_id"] = c.source_post_id
                s.add(GeneratedPost(
                    generated_at=now, post_type=ptype, selection_bucket=(c.cluster or "")[:32],
                    deal_ids=[it.url for it in c.items], rendered_text=text, format_meta=meta,
                    rank_score=perf.get(c.cluster or "", 0.0), status=PostStatus.DRAFT,
                    strategy_rationale=rk,
                    publish_note="Draft from real observed deals (real links). Review before publishing.",
                ))
                created += 1
            result.added = created

        self.bus.publish(Event(event_type=EventType.POST_GENERATED, entity_type="channel",
                               entity_id="owned", data={"drafts": result.added, "source": "observed"},
                               job_id=job.id))
        logger.info("[post_generation_observed] %d candidates -> %d drafts (real links)",
                    result.processed, result.added)
        return result
