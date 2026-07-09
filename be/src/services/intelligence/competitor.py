"""Competitor Intelligence Engine (Phase 5).

Builds behaviour-first competitor profiles, benchmarks our channel against each
competitor, computes content-style similarity, and raises evidence-backed
threats/opportunities. Consumes metrics (does not compute raw metrics or scrape).

Honesty (README/15 core principle — never a number without WHY, and no insight
without evidence): signals are gated by a minimum competitor sample size, since
t.me/s only exposes a recent-post snapshot; below that we withhold the signal.
Forwards/reactions and business categories are unavailable and are not invented.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from src.services.collection.base import BaseCollector, CollectorResult
from src.db.models_competitor_intel import (
    COMPETITOR_INTEL_VERSION,
    CompetitorBenchmark,
    CompetitorProfile,
    CompetitorSignal,
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
# cadence/mix comparisons enough to raise strategic signals.
MIN_SAMPLE_FOR_SIGNALS = 20
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
        signals = self._detect_signals(owned, owned_dates, comp_summaries)

        with session_scope() as s:
            for model in (CompetitorSignal, CompetitorBenchmark, CompetitorProfile):
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
                if n >= MIN_SAMPLE_FOR_SIGNALS:
                    for dim in BENCHMARK_DIMS:
                        ov, cv = owned.get(dim), summ.get(dim)
                        delta = (cv - ov) if (ov is not None and cv is not None) else None
                        s.add(CompetitorBenchmark(
                            intel_version=COMPETITOR_INTEL_VERSION, competitor_id=cid,
                            username=summ["label"], dimension=dim, owned_value=ov,
                            competitor_value=cv, delta=delta, computed_at=now,
                        ))

            for sig in signals:
                s.add(CompetitorSignal(
                    intel_version=COMPETITOR_INTEL_VERSION,
                    competitor_id=sig["competitor_id"], username=sig["username"],
                    signal_type=sig["signal_type"], kind=sig["kind"],
                    description=sig["description"], evidence=sig["evidence"],
                    confidence=sig["confidence"], detected_at=now,
                ))

        self.bus.publish(Event(
            event_type=EventType.COMPETITOR_STRATEGY_UPDATED, entity_type="competitor_set",
            entity_id=str(COMPETITOR_INTEL_VERSION),
            data={"competitors": len(comp_summaries), "signals": len(signals)}, job_id=job.id,
        ))
        for sig in signals:
            etype = (EventType.COMPETITOR_THREAT_DETECTED if sig["signal_type"] == "threat"
                     else EventType.COMPETITOR_OPPORTUNITY_DETECTED)
            self.bus.publish(Event(
                event_type=etype, entity_type="competitor",
                entity_id=str(sig["competitor_id"]), data={"kind": sig["kind"]}, job_id=job.id,
            ))
        logger.info("[competitor_intel] %d profiles, %d signals", len(comp_summaries), len(signals))
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

    def _detect_signals(self, owned: dict, owned_dates: list, comp_summaries: dict) -> list[dict]:
        signals: list[dict] = []
        owned_mix = owned.get("deal_mix") or {}
        owned_total = sum(owned_mix.values()) or 1
        owned_share = {k: v / owned_total for k, v in owned_mix.items()}

        for cid, summ in comp_summaries.items():
            n = summ["post_count"]
            if n < MIN_SAMPLE_FOR_SIGNALS:
                continue  # withhold signals below trustworthy sample
            conf = round(min(1.0, n / FULL_CONFIDENCE_N), 3)
            uname = summ["label"]

            # THREAT: competitor posts markedly more often than us — compared over
            # the SAME window (competitor's observed date range), not full history.
            cppd = summ.get("posts_per_day") or 0.0
            owned_ppd_window = self._owned_cadence_in_window(
                owned_dates, summ.get("first_posted_at"), summ.get("last_posted_at")
            )
            if owned_ppd_window and owned_ppd_window > 0 and cppd > 1.5 * owned_ppd_window:
                signals.append({
                    "competitor_id": cid, "username": uname, "signal_type": "threat",
                    "kind": "higher_posting_cadence",
                    "description": (
                        f"{uname} posts ~{cppd}/day vs our ~{owned_ppd_window}/day "
                        "over the same window."
                    ),
                    "evidence": {"competitor_posts_per_day": cppd,
                                 "owned_posts_per_day_same_window": owned_ppd_window,
                                 "competitor_sample": n,
                                 "window": [str(summ.get("first_posted_at")), str(summ.get("last_posted_at"))]},
                    "confidence": conf,
                })

            # OPPORTUNITY: a DISTINCTIVE deal-type the competitor emphasizes that we
            # underuse. Skip the 'baseline' catch-all cluster — it is not a deal type.
            comp_mix = summ.get("deal_mix") or {}
            comp_total = sum(comp_mix.values()) or 1
            for cluster, cnt in comp_mix.items():
                if cluster is None or cluster.startswith("baseline"):
                    continue
                comp_sh = cnt / comp_total
                our_sh = owned_share.get(cluster, 0.0)
                if comp_sh >= 0.25 and comp_sh > 2 * our_sh:
                    signals.append({
                        "competitor_id": cid, "username": uname, "signal_type": "opportunity",
                        "kind": "underused_deal_type",
                        "description": (
                            f"{uname} allocates {int(comp_sh*100)}% of posts to "
                            f"'{cluster}' vs our {int(our_sh*100)}%."
                        ),
                        "evidence": {"cluster": cluster, "competitor_share": round(comp_sh, 3),
                                     "owned_share": round(our_sh, 3), "competitor_sample": n},
                        "confidence": conf,
                    })
        return signals
