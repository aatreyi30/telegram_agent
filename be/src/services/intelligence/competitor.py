"""Competitor Intelligence Engine (Phase 5).

Builds behaviour-first competitor profiles, benchmarks our channel against each
competitor, and computes content-style similarity. Consumes metrics (does not
compute raw metrics or scrape).

Honesty (README/15 core principle — never a number without WHY, and no insight
without evidence): benchmarks are gated by a minimum competitor sample size,
since t.me/s only exposes a recent-post snapshot; below that we withhold the
comparison. Forwards/reactions and business categories are unavailable and are
not invented.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from src.services.collection.base import BaseCollector, CollectorResult
from src.db.models_competitor_intel import (
    COMPETITOR_INTEL_VERSION,
    CompetitorBenchmark,
    CompetitorProfile,
)
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus
from src.logger import get_logger
from src.services.metrics.competitor_metrics import (
    compute_competitor_behaviours,
    compute_owned_behaviour,
)

logger = get_logger(__name__)

# t.me/s gives a recent-post snapshot; below this many posts we don't trust
# cadence/mix comparisons enough to compute a benchmark.
MIN_SAMPLE_FOR_BENCHMARKS = 20
FULL_CONFIDENCE_N = 30

BENCHMARK_DIMS = [
    "posts_per_day", "avg_text_len", "emoji_rate", "hashtag_rate", "cta_rate",
    "coupon_rate", "multi_deal_rate", "avg_links", "media_rate", "avg_views",
]

# content-style vector for cosine similarity (normalized to comparable scales)
def _style_vector(summ: dict) -> list[float]:
    def g(key, scale=1.0):
        v = summ.get(key)
        return (v / scale) if v is not None else 0.0
    return [
        g("cta_rate"), g("coupon_rate"), g("multi_deal_rate"), g("media_rate"),
        g("emoji_rate", 10.0), g("hashtag_rate", 5.0), g("avg_links", 5.0),
        g("avg_text_len", 500.0),
    ]


def _cosine(a: list[float], b: list[float]) -> float | None:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return None
    return round(dot / (na * nb), 3)


class CompetitorIntelligenceEngine(BaseCollector):
    name = "competitor_intel"
    retryable = False

    def __init__(self) -> None:
        self.bus = get_event_bus()

    def run(self, job) -> CollectorResult:
        result = CollectorResult()
        now = datetime.now(timezone.utc)

        from src.services.metrics.competitor_metrics import _aware

        with session_scope() as s:
            owned_beh = compute_owned_behaviour(s)
            owned = owned_beh.summary()
            owned_dates = sorted(
                d for d in (_aware(p.posted_at) for p in owned_beh.features) if d
            )
            groups, _usernames = compute_competitor_behaviours(s)
            comp_summaries = {cid: g.summary() for cid, g in groups.items()}

        result.processed = len(comp_summaries)
        if not comp_summaries:
            result.skipped_reason = "No normalized competitor posts. Run collect-competitor + normalize."
            return result

        owned_style = _style_vector(owned)

        with session_scope() as s:
            for model in (CompetitorBenchmark, CompetitorProfile):
                s.query(model).filter(
                    model.intel_version == COMPETITOR_INTEL_VERSION
                ).delete()
            s.flush()
            logger.info("[competitor_intel] cleared old intel data for version %d", COMPETITOR_INTEL_VERSION)

            for cid, summ in comp_summaries.items():
                n = summ["post_count"]
                confidence = round(min(1.0, n / FULL_CONFIDENCE_N), 3)
                similarity = _cosine(owned_style, _style_vector(summ))
                logger.info("[competitor_intel] generating profile: competitor_id=%d username=%s post_count=%d merchant_coverage=%s merchant_mix=%s", cid, summ["label"], n, summ.get("merchant_coverage"), summ.get("merchant_mix"))
                s.add(CompetitorProfile(
                    intel_version=COMPETITOR_INTEL_VERSION, competitor_id=cid,
                    username=summ["label"], post_count=n, span_days=summ["span_days"],
                    posts_per_day=summ["posts_per_day"],
                    first_posted_at=summ["first_posted_at"], last_posted_at=summ["last_posted_at"],
                    avg_text_len=summ["avg_text_len"], emoji_rate=summ["emoji_rate"],
                    hashtag_rate=summ["hashtag_rate"], cta_rate=summ["cta_rate"],
                    coupon_rate=summ["coupon_rate"], multi_deal_rate=summ["multi_deal_rate"],
                    avg_links=summ["avg_links"], media_rate=summ["media_rate"],
                    avg_views=summ["avg_views"], views_sample_size=summ["views_sample_size"],
                    top_posting_hour_ist=summ["top_posting_hour_ist"],
                    weekday_distribution=summ["weekday_distribution"],
                    hour_distribution_ist=summ["hour_distribution_ist"],
                    deal_mix=summ["deal_mix"], merchant_mix=summ["merchant_mix"],
                    merchant_coverage=summ["merchant_coverage"], category_available=False,
                    similarity_to_owned=similarity, confidence=confidence, computed_at=now,
                ))
                result.added += 1

                # benchmark rows (only for competitors with a meaningful sample)
                if n >= MIN_SAMPLE_FOR_BENCHMARKS:
                    for dim in BENCHMARK_DIMS:
                        ov, cv = owned.get(dim), summ.get(dim)
                        delta = (cv - ov) if (ov is not None and cv is not None) else None
                        s.add(CompetitorBenchmark(
                            intel_version=COMPETITOR_INTEL_VERSION, competitor_id=cid,
                            username=summ["label"], dimension=dim, owned_value=ov,
                            competitor_value=cv, delta=delta, computed_at=now,
                        ))

        self.bus.publish(Event(
            event_type=EventType.COMPETITOR_STRATEGY_UPDATED, entity_type="competitor_set",
            entity_id=str(COMPETITOR_INTEL_VERSION),
            data={"competitors": len(comp_summaries)}, job_id=job.id,
        ))
        logger.info("[competitor_intel] %d profiles", len(comp_summaries))
        return result

    # ------------------------------------------------------------------ #
    @staticmethod
    def _owned_cadence_in_window(owned_dates: list, start, end) -> float | None:
        """Owned posts/day within [start, end] — the SAME window the competitor
        snapshot covers, so cadence is compared apples-to-apples (not our
        12-month average vs their recent snapshot)."""
        import bisect

        if not owned_dates or start is None or end is None:
            return None
        lo = bisect.bisect_left(owned_dates, start)
        hi = bisect.bisect_right(owned_dates, end)
        count = hi - lo
        span_days = max((end - start).days, 0) + 1
        return round(count / span_days, 3)
