"""Merchant Intelligence Engine (Phase 4).

Consumes per-merchant metrics and produces profiles, transparent scores (with
confidence + sample size), time windows, and evidence-backed opportunities.

Honesty guarantees (README/13 + RULE 1):
  * conversion/discount/category are marked UNAVAILABLE, never estimated;
  * cross-merchant scores are NULL when fewer than 2 merchants have enough data
    to compare (a score from 1 merchant would be meaningless);
  * confidence scales with sample size (few posts -> low confidence);
  * opportunities are only emitted when the data supports them, each with evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.services.collection.base import BaseCollector, CollectorResult
from src.db.models import Merchant
from src.db.models_intelligence import (
    MERCHANT_INTEL_VERSION,
    MerchantMetricWindow,
    MerchantOpportunity,
    MerchantProfile,
)
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus
from src.logger import get_logger
from src.services.metrics.merchant_metrics import WINDOWS, compute_merchant_metrics

logger = get_logger(__name__)

# Sample size at which we treat a merchant's engagement stats as fully
# trustworthy. Below this, confidence scales linearly. (Research notes ~100
# posts for strong patterns; 50 is a pragmatic mid-point for merchant profiles.)
FULL_CONFIDENCE_N = 50
MIN_COMPARE_SAMPLE = 5  # min posts for a merchant to enter cross-merchant scoring


def _minmax(values: dict[str, float]) -> dict[str, float]:
    """Min-max normalize to 0..1. Returns {} if <2 distinct values (not comparable)."""
    vals = list(values.values())
    if len(vals) < 2 or max(vals) == min(vals):
        return {}
    lo, hi = min(vals), max(vals)
    return {k: round((v - lo) / (hi - lo), 3) for k, v in values.items()}


class MerchantIntelligenceEngine(BaseCollector):
    name = "merchant_intel"
    retryable = False

    def __init__(self) -> None:
        self.bus = get_event_bus()

    def run(self, job) -> CollectorResult:
        result = CollectorResult()
        now = datetime.now(timezone.utc)

        with session_scope() as s:
            metrics = compute_merchant_metrics(s)
            summaries = {k: m.summary(now) for k, m in metrics.items()}
            merchant_ids = dict(s.execute(_merchant_id_map()).all())
            owned_total, owned_known = self._owned_merchant_coverage(s)
        # Fraction of our own posts whose merchant is actually resolved. Most
        # GrabOn links are grbn.in shortlinks -> low coverage. We must NOT infer
        # "we don't post merchant X" from absence when coverage is low.
        resolution_coverage = (owned_known / owned_total) if owned_total else 0.0

        result.processed = len(summaries)
        if not summaries:
            result.skipped_reason = (
                "No merchant-attributed posts. Merchant detection needs known link "
                "domains; most GrabOn links are unresolved grbn.in shortlinks."
            )
            return result

        # cross-merchant score inputs (only merchants with enough owned posts)
        comparable = {
            k: v for k, v in summaries.items()
            if v["engagement_sample_size"] >= MIN_COMPARE_SAMPLE
            and v["avg_views_per_day"] is not None
        }
        perf_norm = _minmax({k: v["avg_views_per_day"] for k, v in comparable.items()})
        pop_norm = _minmax({k: float(v["post_count"]) for k, v in summaries.items()})

        opportunities = self._detect_opportunities(
            metrics, summaries, now, resolution_coverage
        )

        with session_scope() as s:
            # replace prior run for this version
            s.query(MerchantMetricWindow).delete()
            s.query(MerchantOpportunity).filter(
                MerchantOpportunity.intel_version == MERCHANT_INTEL_VERSION
            ).delete()
            s.query(MerchantProfile).filter(
                MerchantProfile.intel_version == MERCHANT_INTEL_VERSION
            ).delete()
            s.flush()

            profile_ids: dict[str, int] = {}
            for key, summ in summaries.items():
                span_weeks = summ.get("span_weeks")
                active_weeks = summ.get("active_weeks")
                consistency = (
                    round(min(active_weeks / span_weeks, 1.0), 3)
                    if span_weeks and active_weeks else None
                )
                n = summ["engagement_sample_size"]
                confidence = round(min(1.0, n / FULL_CONFIDENCE_N), 3)

                profile = MerchantProfile(
                    intel_version=MERCHANT_INTEL_VERSION,
                    merchant_key=key,
                    merchant_id=merchant_ids.get(key),
                    post_count_owned=summ["post_count"],
                    first_posted_at=summ["first_posted_at"],
                    last_posted_at=summ["last_posted_at"],
                    days_active=summ["days_active"],
                    active_weeks=active_weeks,
                    posting_consistency=consistency,
                    avg_views=summ["avg_views"],
                    median_views=summ["median_views"],
                    avg_views_per_day=summ["avg_views_per_day"],
                    avg_forwards=summ["avg_forwards"],
                    avg_reactions=summ["avg_reactions"],
                    engagement_sample_size=n,
                    price_min=summ["price_min"],
                    price_max=summ["price_max"],
                    price_avg=summ["price_avg"],
                    price_median=summ["price_median"],
                    price_sample_size=summ["price_sample_size"],
                    discount_available=False,     # needs MRP+current pairing (gated APIs)
                    category_available=False,     # business categories not extracted yet
                    conversion_available=False,   # no click/revenue API (Revenue Data Gap)
                    cluster_distribution=summ["cluster_distribution"],
                    competitor_count=summ["competitor_count"],
                    competitor_post_count=summ["competitor_post_count"],
                    performance_score=perf_norm.get(key),
                    popularity_score=pop_norm.get(key),
                    consistency_score=consistency,
                    opportunity_score=None,  # discrete opportunities carry the signal
                    confidence=confidence,
                    evidence={
                        "engagement_sample_size": n,
                        "comparable_merchants": len(comparable),
                        "note": "scores NULL when <2 comparable merchants",
                    },
                    computed_at=now,
                )
                s.add(profile)
                s.flush()
                profile_ids[key] = profile.id
                result.added += 1

                for w in WINDOWS:
                    ws = metrics[key].window_summary(now, w)
                    s.add(MerchantMetricWindow(
                        profile_id=profile.id, merchant_key=key,
                        window_days=w, post_count=ws["post_count"],
                        avg_views=ws["avg_views"], avg_views_per_day=ws["avg_views_per_day"],
                        avg_forwards=ws["avg_forwards"], computed_at=now,
                    ))

            for opp in opportunities:
                s.add(MerchantOpportunity(
                    intel_version=MERCHANT_INTEL_VERSION,
                    merchant_key=opp["merchant_key"], kind=opp["kind"],
                    description=opp["description"], evidence=opp["evidence"],
                    confidence=opp["confidence"], detected_at=now,
                ))

        for key in summaries:
            self.bus.publish(Event(
                event_type=EventType.MERCHANT_PROFILE_UPDATED,
                entity_type="merchant", entity_id=key, data={}, job_id=job.id,
            ))
        for opp in opportunities:
            self.bus.publish(Event(
                event_type=EventType.MERCHANT_OPPORTUNITY_DETECTED,
                entity_type="merchant", entity_id=opp["merchant_key"],
                data={"kind": opp["kind"]}, job_id=job.id,
            ))
        logger.info(
            "[merchant_intel] %d profiles, %d opportunities, own-merchant "
            "resolution coverage=%.0f%% (low coverage suppresses 'underutilized' signals)",
            len(summaries), len(opportunities), resolution_coverage * 100,
        )
        result.detail["resolution_coverage"] = round(resolution_coverage, 3)
        return result

    # ------------------------------------------------------------------ #
    @staticmethod
    def _owned_merchant_coverage(s) -> tuple[int, int]:
        from sqlalchemy import func, select

        from src.db.models_normalization import NormalizedPost, SourceType

        total = s.scalar(
            select(func.count()).select_from(NormalizedPost).where(
                NormalizedPost.source_type == SourceType.OWNED
            )
        ) or 0
        known = s.scalar(
            select(func.count()).select_from(NormalizedPost).where(
                NormalizedPost.source_type == SourceType.OWNED,
                NormalizedPost.primary_merchant_key.isnot(None),
            )
        ) or 0
        return total, known

    # 'we don't post merchant X' is only trustworthy when we can actually see
    # most of our own merchants. Below this, suppress the underutilized signal.
    MIN_COVERAGE_FOR_ABSENCE = 0.6

    def _detect_opportunities(self, metrics, summaries, now, resolution_coverage) -> list[dict]:
        opps: list[dict] = []
        for key, summ in summaries.items():
            # (a) used by competitors, absent from our channel -> underutilized.
            #     Only trustworthy when our own merchant resolution is high enough
            #     that "0 owned posts" really means we don't post it.
            if (
                summ["post_count"] == 0
                and summ["competitor_post_count"] > 0
                and resolution_coverage >= self.MIN_COVERAGE_FOR_ABSENCE
            ):
                opps.append({
                    "merchant_key": key,
                    "kind": "underutilized_vs_competitors",
                    "description": (
                        f"{key} appears in {summ['competitor_count']} competitor "
                        f"channel(s) ({summ['competitor_post_count']} posts) but not "
                        "in our channel."
                    ),
                    "evidence": {
                        "competitor_post_count": summ["competitor_post_count"],
                        "competitor_count": summ["competitor_count"],
                        "own_post_count": 0,
                    },
                    "confidence": round(min(1.0, summ["competitor_post_count"] / 10), 3),
                })
            # (b) engagement trending up: recent 7d vs 30d age-normalized views
            w7 = metrics[key].window_summary(now, 7)
            w30 = metrics[key].window_summary(now, 30)
            if (
                w7["post_count"] >= 3 and w30["post_count"] >= 6
                and w7["avg_views_per_day"] and w30["avg_views_per_day"]
                and w7["avg_views_per_day"] > 1.2 * w30["avg_views_per_day"]
            ):
                lift = round(w7["avg_views_per_day"] / w30["avg_views_per_day"] - 1, 3)
                opps.append({
                    "merchant_key": key,
                    "kind": "engagement_trending_up",
                    "description": (
                        f"{key} views/day up {int(lift*100)}% over the last "
                        "7 days vs the 30-day baseline."
                    ),
                    "evidence": {
                        "views_per_day_7d": round(w7["avg_views_per_day"], 2),
                        "views_per_day_30d": round(w30["avg_views_per_day"], 2),
                        "posts_7d": w7["post_count"], "posts_30d": w30["post_count"],
                    },
                    "confidence": round(min(1.0, w7["post_count"] / 10), 3),
                })
        return opps


def _merchant_id_map():
    from sqlalchemy import select

    return select(Merchant.key, Merchant.id)
