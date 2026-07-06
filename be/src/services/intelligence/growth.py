"""Growth Engine (Phase 7).

Synthesizes a channel strategy + ranked, evidence-backed recommendations from
the intelligence produced in Phases 4–6. It defines WHAT to do; it never writes
posts (Phase 9) and never invents an unsupported recommendation.

Two auto-detected modes (README/25):
  * OPTIMIZATION — >=7 days AND >=50 posts AND engagement: personalized from the
    Channel Learning Engine (Phase 6) + merchant/competitor intelligence.
  * COLD START   — otherwise: bootstrap from competitor profiles (Phase 5).
"""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from src.services.collection.base import BaseCollector, CollectorResult
from src.db.models import Post
from src.db.models_classification import PostClassification, PostTypeCluster
from collections import Counter

from src.db.models_competitor_intel import (
    COMPETITOR_INTEL_VERSION,
    CompetitorProfile,
    CompetitorSignal,
)
from src.db.models_growth import (
    GROWTH_VERSION,
    GrowthMode,
    GrowthRecommendation,
    GrowthStrategy,
)
from src.db.models_learning import (
    LEARNING_VERSION,
    ChannelStyleProfile,
    LearningRecord,
    PostTypePerformance,
)
from src.db.models_normalization import NormalizedPost, SourceType
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus
from src.logger import get_logger

logger = get_logger(__name__)

MIN_POSTS_FOR_OPTIMIZATION = 50
MIN_DAYS_FOR_OPTIMIZATION = 7


def plain_label(descriptor: str | None) -> str:
    """Translate a learned-cluster feature signature into a human-readable post
    type. Presentation only — describes the measured features in plain words; it
    does not define or hardcode a category taxonomy."""
    d = (descriptor or "").lower()
    if "coupon" in d:
        return "coupon-code deals"
    if "many-links" in d or "multi-deal" in d:
        return "multi-product loot collections (several deal links in one post)"
    if "wide-price-range" in d or "many-prices" in d:
        return "mixed-price bundles"
    if "single-item" in d:
        return "single-item deals"
    if "high-price" in d:
        return "higher-priced single deals"
    if "low-price" in d:
        return "budget / low-priced single deals"
    if "baseline" in d:
        return "general/other posts"
    return descriptor or "posts"


class GrowthEngine(BaseCollector):
    name = "growth"
    retryable = False

    def __init__(self) -> None:
        self.bus = get_event_bus()

    def run(self, job) -> CollectorResult:
        result = CollectorResult()
        now = datetime.now(timezone.utc)
        with session_scope() as s:
            mode, basis = self._detect_mode(s, now)
            if mode == GrowthMode.OPTIMIZATION:
                strategy, recs = self._optimization(s, now, basis)
            else:
                strategy, recs = self._cold_start(s, now, basis)

        if strategy is None:
            result.skipped_reason = (
                "Insufficient intelligence to build a strategy. Run the upstream "
                "engines first (normalize, classify, learn / competitor-intel)."
            )
            return result

        # rank recommendations by score (confidence * impact), then assign priority
        recs.sort(key=lambda r: r.pop("_score"), reverse=True)
        with session_scope() as s:
            for model in (GrowthRecommendation, GrowthStrategy):
                s.query(model).filter(model.growth_version == GROWTH_VERSION).delete()
            s.flush()
            strat = GrowthStrategy(
                growth_version=GROWTH_VERSION, mode=mode, generated_at=now,
                channel_type=strategy["channel_type"], blueprint=strategy["blueprint"],
                data_basis=basis, confidence=strategy["confidence"],
            )
            s.add(strat)
            s.flush()
            for i, r in enumerate(recs):
                s.add(GrowthRecommendation(
                    growth_version=GROWTH_VERSION, strategy_id=strat.id,
                    category=r["category"], recommendation=r["recommendation"],
                    reasoning=r["reasoning"], evidence=r["evidence"],
                    confidence=r["confidence"], priority=i + 1,
                    expected_outcome=r.get("expected_outcome"), generated_at=now,
                ))
            result.added = 1 + len(recs)

        self.bus.publish(Event(
            event_type=EventType.GROWTH_STRATEGY_GENERATED, entity_type="channel",
            entity_id="owned", data={"mode": mode, "recommendations": len(recs)}, job_id=job.id,
        ))
        logger.info("[growth] mode=%s, %d recommendations", mode, len(recs))
        return result

    # ------------------------------------------------------------------ #
    def _detect_mode(self, s, now) -> tuple[str, dict]:
        total = s.scalar(
            select(func.count()).select_from(NormalizedPost).where(
                NormalizedPost.source_type == SourceType.OWNED
            )
        ) or 0
        first, last = s.execute(
            select(func.min(Post.posted_at), func.max(Post.posted_at))
        ).one()
        span_days = None
        if first and last:
            fa = first if first.tzinfo else first.replace(tzinfo=timezone.utc)
            la = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
            span_days = (la - fa).days + 1
        has_engagement = (s.scalar(
            select(func.count()).select_from(Post).where(Post.views.isnot(None))
        ) or 0) > 0
        basis = {"owned_posts": total, "span_days": span_days, "has_engagement": has_engagement}
        if (
            total >= MIN_POSTS_FOR_OPTIMIZATION
            and (span_days or 0) >= MIN_DAYS_FOR_OPTIMIZATION
            and has_engagement
        ):
            return GrowthMode.OPTIMIZATION, basis
        return GrowthMode.COLD_START, basis

    # ---------------- OPTIMIZATION MODE ---------------- #
    def _optimization(self, s, now, basis):
        style = s.scalar(
            select(ChannelStyleProfile).where(
                ChannelStyleProfile.learning_version == LEARNING_VERSION
            )
        )
        perf = s.scalars(
            select(PostTypePerformance)
            .where(PostTypePerformance.learning_version == LEARNING_VERSION)
            .order_by(PostTypePerformance.rank_by_views_per_day)
        ).all()
        records = s.scalars(
            select(LearningRecord).where(LearningRecord.learning_version == LEARNING_VERSION)
        ).all()
        if style is None or not perf:
            return None, []
        by_cat: dict[str, list] = {}
        for r in records:
            by_cat.setdefault(r.category, []).append(r)

        channel_type, ct_evidence = self._derive_channel_type(perf)
        content_mix = self._content_mix(perf)
        blueprint = {
            "posting_frequency_baseline": style.posts_per_day,
            "recommended_hours_ist": [h for h, _ in (style.top_hours_ist or [])][:3],
            "content_mix": content_mix,
            "emoji_strategy": self._positive_emojis(by_cat.get("emoji", [])),
            "cta_note": self._one_statement(by_cat.get("cta")),
            "media_note": self._one_statement(by_cat.get("media")),
            "merchant_focus": self._one_statement(by_cat.get("merchant")),
        }
        strategy = {
            "channel_type": channel_type,
            "blueprint": blueprint,
            "confidence": style.confidence,
        }

        recs: list[dict] = []

        def rec(category, text, reasoning, evidence, confidence, impact, outcome=None):
            recs.append({
                "category": category, "recommendation": text, "reasoning": reasoning,
                "evidence": evidence, "confidence": round(confidence, 3),
                "expected_outcome": outcome, "_score": round(confidence * impact, 4),
            })

        base = self._baseline_from(by_cat)

        # (1) emphasize top post type — concrete numbers + a target share
        top = next((p for p in perf if p.post_count >= 20 and p.avg_views_per_day), None)
        if top and base:
            lift = self._lift(top.avg_views_per_day, base)
            mult = top.avg_views_per_day / base
            target = min(0.20, round(top.share * 3, 2))  # a modest, bounded target share
            label = plain_label(top.post_type)
            rec("post_type",
                f"Post more {label}: ~{top.avg_views_per_day:.0f} views/day vs your "
                f"{base:.0f} channel average ({mult:.1f}x). They are only {top.share*100:.0f}% "
                f"of your posts — grow toward ~{target*100:.0f}%.",
                f"Highest age-normalized views of any post type, measured over {top.post_count} posts.",
                {"post_type": top.post_type, "plain_label": label,
                 "avg_views_per_day": top.avg_views_per_day, "channel_avg": round(base, 1),
                 "multiple_vs_avg": round(mult, 2), "current_share": top.share,
                 "target_share": target, "sample": top.post_count},
                top.confidence, impact=abs(lift) / 100 + 0.5,
                outcome=f"If you shift ~10% of volume here, expect materially higher average reach.")

        # (2) de-emphasize a meaningful underperformer — concrete numbers
        bottom = next((p for p in reversed(perf)
                       if p.post_count >= 20 and p.avg_views_per_day and p.share >= 0.1), None)
        if bottom and base and (not top or bottom.post_type != top.post_type):
            lift = self._lift(bottom.avg_views_per_day, base)
            label = plain_label(bottom.post_type)
            rec("post_type",
                f"Cut back on {label}: only ~{bottom.avg_views_per_day:.0f} views/day "
                f"({lift:+.0f}% vs your {base:.0f} average) yet they are {bottom.share*100:.0f}% "
                "of everything you post.",
                f"Consistently below-average age-normalized views over {bottom.post_count} posts; "
                "they consume volume that your top types would monetize better.",
                {"post_type": bottom.post_type, "plain_label": label,
                 "avg_views_per_day": bottom.avg_views_per_day, "channel_avg": round(base, 1),
                 "current_share": bottom.share, "sample": bottom.post_count},
                bottom.confidence, impact=abs(lift) / 100 + 0.3,
                outcome="Frees posting slots for higher-reach content.")

        # (3) timing — a full-day POSTING SCHEDULE (you post many times/day, so this
        # distributes volume across the day weighted to stronger windows, never one hour)
        for lr in by_cat.get("timing", []):
            ev = lr.evidence or {}
            plan = self._build_posting_plan(style.posts_per_day, ev.get("hourly_all"))
            if plan:
                blueprint["posting_plan"] = plan
                parts_txt = "; ".join(
                    f"{p['part']} {p['hours']} → ~{p['recommended_posts_per_day']} posts ({p['action']})"
                    for p in plan
                )
                text = (f"Spread your ~{style.posts_per_day:.0f} posts/day across the day, "
                        f"weighted to your strongest windows: {parts_txt}.")
                exp = ev.get("experimental_windows") or []
                outcome = None
                if exp:
                    ehrs = ", ".join(f"{e[0]:02d}:00" for e in exp)
                    outcome = (f"The late-night hours ({ehrs}) show higher per-post views on small "
                               "samples — worth a controlled test, but keep the bulk in proven windows.")
                rec("timing", text, lr.statement, {**ev, "posting_plan": plan},
                    lr.confidence, impact=0.5, outcome=outcome)
            else:
                rec("timing", lr.statement.split(".")[0] + ".", lr.statement, ev, lr.confidence, impact=0.4)

        # (4) positive emojis — with concrete lift
        for lr in sorted(by_cat.get("emoji", []), key=lambda x: (x.metric_value or 0), reverse=True)[:2]:
            if lr.metric_value and lr.comparison_value and lr.metric_value > lr.comparison_value:
                emoji = (lr.evidence or {}).get("emoji", "")
                emoji_lift = self._lift(lr.metric_value, lr.comparison_value)
                rec("format",
                    f"Include {emoji} in deal posts — posts using it average {emoji_lift:+.0f}% "
                    "views vs your channel average.",
                    lr.statement + " (Correlational, but a cheap, safe format tweak to adopt.)",
                    lr.evidence or {}, lr.confidence, impact=0.5)

        # (5) media (correlational -> phrased as preference/test)
        for lr in by_cat.get("media", []):
            if lr.metric_value and lr.comparison_value and lr.metric_value < lr.comparison_value:
                media_lift = self._lift(lr.metric_value, lr.comparison_value)
                rec("media",
                    f"Favor concise text+link deal drops: media-heavy posts get {media_lift:+.0f}% "
                    "views vs text-only in your history.",
                    lr.statement + " (Correlational — verify with an A/B test.)",
                    lr.evidence or {}, lr.confidence * 0.8, impact=0.5)

        # (6) cta (correlational -> A/B test)
        for lr in by_cat.get("cta", []):
            if lr.metric_value and lr.comparison_value and lr.metric_value < lr.comparison_value:
                rec("cta", "A/B test leaner call-to-action wording.",
                    lr.statement + " (Correlational — test before removing CTAs.)",
                    lr.evidence or {}, lr.confidence * 0.7, impact=0.3)

        # (7) merchant focus (only emitted by Phase 6 when >=2 merchants are comparable
        # and the best one actually outperforms — so it is safe to surface in full)
        for lr in by_cat.get("merchant", []):
            merchant = (lr.evidence or {}).get("merchant", "the top merchant")
            rec("merchant", f"Prioritize {merchant} deals — {lr.statement}",
                lr.statement, lr.evidence or {}, lr.confidence, impact=0.4)

        # (8) frequency vs competitors (Phase 5 threats)
        threats = s.scalars(
            select(CompetitorSignal).where(
                CompetitorSignal.intel_version == COMPETITOR_INTEL_VERSION,
                CompetitorSignal.signal_type == "threat",
                CompetitorSignal.kind == "higher_posting_cadence",
            ).order_by(CompetitorSignal.confidence.desc())
        ).all()
        if threats:
            t = threats[0]
            ev = t.evidence or {}
            cppd = ev.get("competitor_posts_per_day")
            oppd = ev.get("owned_posts_per_day_same_window")
            uname = t.username or "a category leader"
            text = (f"Raise posting cadence in peak windows: {uname} posted ~{cppd}/day vs your "
                    f"~{oppd}/day in the same window."
                    if cppd and oppd else
                    "Increase posting cadence during peak windows to match category leaders.")
            rec("frequency", text,
                f"{t.description} Sustained higher cadence by leaders can crowd out your reach.",
                ev, t.confidence, impact=0.6,
                outcome="More impressions during high-competition windows.")

        # (9) competitor patterns — what similar, high-sample competitors emphasize
        #     that we underuse, CROSS-CHECKED against our own performance so we never
        #     recommend copying something our own data shows hurts us.
        own_mix = {p["post_type"]: (p.get("current_share") or 0.0) for p in (blueprint.get("content_mix") or [])}
        # perf is a list of PostTypePerformance rows here — build a {type: views/day} lookup
        perf_by_type = {p.post_type: p.avg_views_per_day for p in perf if p.avg_views_per_day}
        perf_median = statistics.median(list(perf_by_type.values())) if perf_by_type else None
        comps = s.scalars(
            select(CompetitorProfile)
            .where(CompetitorProfile.intel_version == COMPETITOR_INTEL_VERSION,
                   CompetitorProfile.post_count >= 20)
            .order_by(CompetitorProfile.similarity_to_owned.desc())
        ).all()
        emitted = 0
        for cp in comps:
            if emitted >= 2:
                break
            mix = cp.deal_mix or {}
            total = sum(mix.values()) or 1
            for cluster, cnt in sorted(mix.items(), key=lambda kv: kv[1], reverse=True):
                if not cluster or cluster.startswith("baseline"):
                    continue
                comp_share = cnt / total
                our_share = own_mix.get(cluster, 0.0)
                if comp_share < 0.25 or comp_share <= our_share + 0.15:
                    continue  # only when the leader leans on it much more than we do
                our_vpd = perf_by_type.get(cluster)
                # cross-check with OUR OWN performance for this type
                if our_vpd is not None and perf_median is not None:
                    verdict = ("your own data agrees — this type is an above-average performer "
                               f"for you (~{our_vpd:.0f} views/day)" if our_vpd >= perf_median
                               else "but your own data shows this type is a below-average performer "
                               f"for you (~{our_vpd:.0f} views/day), so test cautiously")
                    conf = round(min(1.0, cp.post_count / 40) * (0.9 if our_vpd >= perf_median else 0.5), 3)
                else:
                    verdict = "you have little of your own data on this type yet — worth a controlled test"
                    conf = round(min(1.0, cp.post_count / 40) * 0.5, 3)
                rec("competitor",
                    f"Test more {plain_label(cluster)} like {cp.username}: they put "
                    f"{int(comp_share*100)}% of posts there vs your {int(our_share*100)}% — {verdict}.",
                    f"{cp.username} is one of your most similar competitors "
                    f"(similarity {cp.similarity_to_owned}); this blends what a category leader does "
                    "with your own performance. (Competitor engagement on t.me/s is rounded and "
                    "sample-limited — treat as a lead, not a guarantee.)",
                    {"competitor": cp.username, "cluster": cluster,
                     "competitor_share": round(comp_share, 3), "our_share": round(our_share, 3),
                     "our_views_per_day": our_vpd, "competitor_posts": cp.post_count},
                    conf, impact=0.5)
                emitted += 1
                break

        # (10) content diversity (recent 30d concentration)
        div = self._recent_diversity(s, now)
        if div and div["top_share"] > 0.7:
            rec("diversity",
                f"Diversify recent content — '{div['top_type']}' is {div['top_share']*100:.0f}% "
                "of the last 30 days.",
                "Narrow content mix risks audience fatigue; historical variety spreads reach.",
                div, 0.6, impact=0.5)

        return strategy, recs

    # ---------------- COLD START MODE ---------------- #
    def _cold_start(self, s, now, basis):
        profiles = s.scalars(
            select(CompetitorProfile)
            .where(CompetitorProfile.intel_version == COMPETITOR_INTEL_VERSION)
            .order_by(CompetitorProfile.post_count.desc())
        ).all()
        usable = [p for p in profiles if p.post_count >= 20]
        if not usable:
            return None, []

        def med(attr):
            vals = [getattr(p, attr) for p in usable if getattr(p, attr) is not None]
            return round(statistics.median(vals), 3) if vals else None

        # aggregate competitor deal mix
        deal_counter: Counter = Counter()
        for p in usable:
            for k, v in (p.deal_mix or {}).items():
                deal_counter[k] += v
        top_hours = Counter()
        for p in usable:
            if p.top_posting_hour_ist is not None:
                top_hours[p.top_posting_hour_ist] += 1

        channel_type = self._channel_type_from_mix(dict(deal_counter))
        blueprint = {
            "posting_frequency_baseline": med("posts_per_day"),
            "recommended_hours_ist": [h for h, _ in top_hours.most_common(3)],
            "content_mix_reference": dict(deal_counter.most_common(6)),
            "cta_rate_reference": med("cta_rate"),
            "media_rate_reference": med("media_rate"),
            "emoji_rate_reference": med("emoji_rate"),
        }
        strategy = {"channel_type": channel_type, "blueprint": blueprint,
                    "confidence": round(min(1.0, len(usable) / 5), 3)}

        recs: list[dict] = []
        conf = strategy["confidence"]
        recs.append({
            "category": "frequency",
            "recommendation": f"Start at ~{blueprint['posting_frequency_baseline']} posts/day.",
            "reasoning": "Median observed cadence of comparable competitor channels.",
            "evidence": {"competitors": [p.username for p in usable],
                         "median_posts_per_day": blueprint["posting_frequency_baseline"]},
            "confidence": conf, "expected_outcome": "Match category baseline activity.",
            "_score": conf * 0.6,
        })
        if blueprint["recommended_hours_ist"]:
            recs.append({
                "category": "timing",
                "recommendation": f"Post around {blueprint['recommended_hours_ist']} IST.",
                "reasoning": "Peak posting hours of comparable competitors.",
                "evidence": {"hours_ist": blueprint["recommended_hours_ist"]},
                "confidence": conf, "expected_outcome": None, "_score": conf * 0.4,
            })
        if deal_counter:
            top_type = deal_counter.most_common(1)[0][0]
            recs.append({
                "category": "content_mix",
                "recommendation": f"Lead with '{top_type}' style posts to enter the category.",
                "reasoning": "Most common post type across comparable competitors.",
                "evidence": {"deal_mix": dict(deal_counter.most_common(6))},
                "confidence": conf, "expected_outcome": None, "_score": conf * 0.5,
            })
        return strategy, recs

    # day-parts are time buckets for a readable schedule (not business categories)
    _DAY_PARTS = [
        ("Late night", "00:00–05:00", range(0, 6)),
        ("Morning", "06:00–11:00", range(6, 12)),
        ("Afternoon", "12:00–17:00", range(12, 18)),
        ("Evening", "18:00–23:00", range(18, 24)),
    ]

    def _build_posting_plan(self, posts_per_day, hourly_all) -> list[dict] | None:
        """Distribute the daily posting budget across day-parts, shifting volume
        toward higher-performing parts while keeping presence in every active part
        (you post many times/day — never collapse to a single hour)."""
        if not posts_per_day or not hourly_all:
            return None
        # hourly_all: [[hour, avg_views_per_day, n_posts], ...]
        by_hour = {int(h): (avg, n) for h, avg, n in hourly_all}
        total_n = sum(n for _, n in by_hour.values()) or 1
        overall_avg = sum(avg * n for avg, n in by_hour.values()) / total_n or 1.0

        parts = []
        for name, label, hours in self._DAY_PARTS:
            ns = [by_hour[h][1] for h in hours if h in by_hour]
            avgs = [by_hour[h] for h in hours if h in by_hour]
            part_n = sum(ns)
            if part_n == 0:
                continue
            part_avg = sum(a * n for a, n in avgs) / part_n
            current_share = part_n / total_n
            parts.append({
                "part": name, "hours": label, "current_share": current_share,
                "part_avg_views_per_day": part_avg,
                # weight current volume by relative performance -> shift toward winners
                "raw_weight": current_share * (part_avg / overall_avg),
            })
        if not parts:
            return None
        wsum = sum(p["raw_weight"] for p in parts) or 1.0
        plan = []
        for p in parts:
            rec_share = p["raw_weight"] / wsum
            cur_ppd = round(posts_per_day * p["current_share"], 1)
            rec_ppd = max(1, round(posts_per_day * rec_share))  # keep >=1: never zero a part
            action = ("increase" if rec_ppd > cur_ppd * 1.15
                      else "reduce" if rec_ppd < cur_ppd * 0.85 else "maintain")
            plan.append({
                "part": p["part"], "hours": p["hours"],
                "current_posts_per_day": cur_ppd,
                "recommended_posts_per_day": rec_ppd,
                "avg_views_per_day": round(p["part_avg_views_per_day"], 1),
                "action": action,
            })
        return plan

    # ---------------- helpers ---------------- #
    @staticmethod
    def _lift(value, baseline):
        if not value or not baseline:
            return 0.0
        return (value / baseline - 1) * 100

    @staticmethod
    def _baseline_from(by_cat) -> float | None:
        for cat in ("post_type", "cta", "media", "emoji", "timing", "merchant"):
            for lr in by_cat.get(cat, []):
                if lr.comparison_value:
                    return lr.comparison_value
        return None

    def _content_mix(self, perf) -> list[dict]:
        vals = [p.avg_views_per_day for p in perf if p.avg_views_per_day]
        med = statistics.median(vals) if vals else None
        out = []
        for p in perf:
            action = "maintain"
            if med and p.avg_views_per_day:
                if p.avg_views_per_day >= 1.25 * med:
                    action = "increase"
                elif p.avg_views_per_day <= 0.75 * med:
                    action = "decrease"
            out.append({
                "post_type": p.post_type, "current_share": p.share,
                "avg_views_per_day": p.avg_views_per_day, "action": action,
            })
        return out

    def _derive_channel_type(self, perf):
        # dominant post type by volume -> channel-type label (derived, not hardcoded)
        top = max(perf, key=lambda p: p.post_count) if perf else None
        label = self._channel_type_from_descriptor(top.post_type) if top else "unknown"
        return label, {"dominant_post_type": top.post_type if top else None}

    @staticmethod
    def _channel_type_from_descriptor(desc: str | None) -> str:
        d = (desc or "").lower()
        if "coupon" in d:
            return "coupon-led"
        if "multi-deal" in d or "many-links" in d:
            return "loot-led"
        if "single-item" in d:
            return "single-deal-led"
        return "hybrid"

    def _channel_type_from_mix(self, mix: dict) -> str:
        if not mix:
            return "unknown"
        top = max(mix.items(), key=lambda kv: kv[1])[0]
        return self._channel_type_from_descriptor(top)

    @staticmethod
    def _positive_emojis(emoji_records) -> list[str]:
        out = []
        for lr in emoji_records:
            if lr.metric_value and lr.comparison_value and lr.metric_value > lr.comparison_value:
                e = (lr.evidence or {}).get("emoji")
                if e:
                    out.append(e)
        return out

    @staticmethod
    def _one_statement(records) -> str | None:
        return records[0].statement if records else None

    def _recent_diversity(self, s, now) -> dict | None:
        cutoff = now - timedelta(days=30)
        rows = s.execute(
            select(PostTypeCluster.descriptor, func.count())
            .select_from(PostClassification)
            .join(PostTypeCluster, PostTypeCluster.id == PostClassification.cluster_id)
            .join(NormalizedPost, NormalizedPost.id == PostClassification.normalized_post_id)
            .join(Post, Post.id == NormalizedPost.source_id)
            .where(NormalizedPost.source_type == SourceType.OWNED, Post.posted_at >= cutoff)
            .group_by(PostTypeCluster.descriptor)
        ).all()
        total = sum(c for _, c in rows)
        if total < 20:
            return None
        top_type, top_count = max(rows, key=lambda kv: kv[1])
        return {"top_type": top_type, "top_share": round(top_count / total, 3),
                "recent_posts": total, "window_days": 30}
