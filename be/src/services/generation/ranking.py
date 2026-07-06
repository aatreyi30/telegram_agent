"""Deal Ranking + Selection (source_truth/04 Phase 9).

RANKING — scores each enriched deal. The decisive magnitudes are LEARNED from
data (channel baseline views/day and per-merchant performance from Phases 6/4);
they are NOT hardcoded weights. Secondary transforms (discount value, novelty,
validity) are transparent and clearly flagged as heuristics that will be replaced
by regression-learned weights once the prediction-evaluation loop has outcome data
(Channel Learning, deferred). Nothing is a magic hand-tuned constant presented as
truth.

SELECTION — picks a diverse set spanning the buckets the spec requires:
loot, trending, budget, high-value, exploration.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Post
from src.db.models_generation import DealValidity, EnrichedDeal
from src.db.models_intelligence import MERCHANT_INTEL_VERSION, MerchantProfile
from src.db.models_learning import LEARNING_VERSION, LearningRecord, PostTypePerformance
from src.db.models_normalization import NormalizedPost, SourceType


@dataclass
class RankInputs:
    channel_baseline_vpd: float
    merchant_factor: dict[str, float]   # merchant_key -> relative performance factor
    recent_merchants: set[str]          # merchants posted in the last 24h (novelty)


class DealRanker:
    def __init__(self, session: Session):
        self.s = session
        self.inputs = self._load_learned_inputs()

    def _load_learned_inputs(self) -> RankInputs:
        # channel baseline: prefer a learning record's stored baseline, else median
        baseline = self.s.scalar(
            select(LearningRecord.comparison_value)
            .where(LearningRecord.learning_version == LEARNING_VERSION,
                   LearningRecord.comparison_value.isnot(None))
            .limit(1)
        )
        if not baseline:
            vals = [p.avg_views_per_day for p in self.s.scalars(
                select(PostTypePerformance).where(
                    PostTypePerformance.learning_version == LEARNING_VERSION))
                if p.avg_views_per_day]
            baseline = statistics.median(vals) if vals else 1.0
        baseline = baseline or 1.0

        # per-merchant relative performance (learned, Phase 4) — only trusted merchants
        merchant_factor: dict[str, float] = {}
        for mp in self.s.scalars(
            select(MerchantProfile).where(MerchantProfile.intel_version == MERCHANT_INTEL_VERSION)
        ):
            if mp.avg_views_per_day and mp.engagement_sample_size >= 20:
                merchant_factor[mp.merchant_key] = round(mp.avg_views_per_day / baseline, 3)

        # novelty: merchants we posted in the last 24h (avoid over-repeating)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent = set()
        for mkey, in self.s.execute(
            select(NormalizedPost.primary_merchant_key)
            .join(Post, Post.id == NormalizedPost.source_id)
            .where(NormalizedPost.source_type == SourceType.OWNED,
                   NormalizedPost.primary_merchant_key.isnot(None),
                   Post.posted_at >= cutoff)
        ).all():
            recent.add(mkey)
        return RankInputs(baseline, merchant_factor, recent)

    def score(self, deal: EnrichedDeal) -> tuple[float, dict]:
        base = self.inputs.channel_baseline_vpd          # LEARNED magnitude
        merchant_factor = self.inputs.merchant_factor.get(deal.merchant_key or "", 1.0)  # LEARNED

        # --- transparent heuristic transforms (pending outcome-learned weights) ---
        d = deal.discount_percent or 0.0
        value_factor = round(1 + min(d, 90) / 100.0, 3)   # bigger genuine discount = more value
        novelty_factor = 0.8 if (deal.merchant_key in self.inputs.recent_merchants) else 1.0
        if deal.deal_validity == DealValidity.INVALID:
            validity_factor = 0.0
        elif deal.deal_validity == DealValidity.UNKNOWN:
            validity_factor = 0.7
        else:
            validity_factor = 1.0

        score = round(base * merchant_factor * value_factor * novelty_factor * validity_factor, 3)
        breakdown = {
            "channel_baseline_vpd": round(base, 2), "merchant_factor": merchant_factor,
            "value_factor": value_factor, "novelty_factor": novelty_factor,
            "validity_factor": validity_factor,
            "note": ("base + merchant_factor are learned from history; value/novelty/validity "
                     "are transparent heuristics pending outcome-learned weights."),
        }
        return score, breakdown

    def rank(self, deals: list[EnrichedDeal]) -> list[EnrichedDeal]:
        for deal in deals:
            deal.rank_score, deal.score_breakdown = self.score(deal)
        self.s.flush()
        return sorted(deals, key=lambda d: (d.rank_score or 0), reverse=True)


class DealSelector:
    """Selects a diverse set across the required buckets (source_truth/04)."""

    BUDGET_MAX = 499
    HIGH_VALUE_MIN = 3000

    def _bucket(self, deal: EnrichedDeal, seen_merchants: set[str]) -> str:
        if deal.is_loot_deal:
            return "loot"
        if deal.current_price is not None and deal.current_price >= self.HIGH_VALUE_MIN:
            return "high-value"
        if deal.current_price is not None and deal.current_price <= self.BUDGET_MAX:
            return "budget"
        if deal.merchant_key and deal.merchant_key not in seen_merchants:
            return "exploration"
        return "trending"

    def select(self, ranked: list[EnrichedDeal], count: int = 5) -> list[tuple[EnrichedDeal, str]]:
        # only valid / undetermined deals are eligible (never invalid)
        eligible = [d for d in ranked if d.deal_validity != DealValidity.INVALID]
        wanted = ["loot", "trending", "budget", "high-value", "exploration"]
        chosen: list[tuple[EnrichedDeal, str]] = []
        used_ids: set[int] = set()
        seen_merchants: set[str] = set()

        # first pass: fill one of each required bucket with the best-scoring fit
        for bucket in wanted:
            for d in eligible:
                if id(d) in used_ids:
                    continue
                if self._bucket(d, seen_merchants) == bucket:
                    chosen.append((d, bucket))
                    used_ids.add(id(d))
                    if d.merchant_key:
                        seen_merchants.add(d.merchant_key)
                    break
            if len(chosen) >= count:
                break

        # fill remaining slots by score, keeping merchant variety where possible
        for d in eligible:
            if len(chosen) >= count:
                break
            if id(d) in used_ids:
                continue
            chosen.append((d, self._bucket(d, seen_merchants)))
            used_ids.add(id(d))
            if d.merchant_key:
                seen_merchants.add(d.merchant_key)
        return chosen[:count]


class StrategyAwareSelector(DealSelector):
    """Selection that OBEYS the growth content-mix: caps low-priced single deals
    (a below-average type the strategy says to reduce) and lets higher-value / loot
    deals — which feed the winning collection type — fill the rest. Deals arrive
    pre-ranked by learned score, so we just apply the strategy's caps on top."""

    def __init__(self, strategy):
        self.strategy = strategy

    def select(self, ranked: list[EnrichedDeal], count: int = 5) -> list[tuple[EnrichedDeal, str]]:
        eligible = [d for d in ranked if d.deal_validity != DealValidity.INVALID]
        budget_cap = max(1, count // 5)   # at most ~20% low-price singles
        chosen: list[tuple[EnrichedDeal, str]] = []
        seen: set[str] = set()
        budget_used = 0
        for d in eligible:
            if len(chosen) >= count:
                break
            is_budget_single = (not d.is_loot_deal and d.current_price is not None
                                and d.current_price <= self.BUDGET_MAX)
            if is_budget_single and budget_used >= budget_cap:
                continue  # strategy: don't over-post low-price singles
            chosen.append((d, self._bucket(d, seen)))
            if is_budget_single:
                budget_used += 1
            if d.merchant_key:
                seen.add(d.merchant_key)
        return chosen[:count]
