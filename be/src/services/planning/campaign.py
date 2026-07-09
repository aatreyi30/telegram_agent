"""Campaign & Planning Engine (Phase 10).

Turns the Growth blueprint (Phase 7) + learnings (Phase 6) + merchant/competitor
intelligence (Phases 4/5) + the sale calendar into structured DAILY, WEEKLY and
EVENT plans: how many posts, in which windows, across which deal-types and
merchants, with risks, an expected-outcome estimate, confidence, and the evidence
each recommendation rests on.

Creates plans only — no captions, no publishing, no raw-metric calculation.
"""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.services.collection.base import BaseCollector, CollectorResult
from src.db.models import Post
from src.db.models_campaign import (
    CAMPAIGN_VERSION,
    CampaignPlan,
    DateConfidence,
    PlanType,
    SaleEvent,
)
from src.db.models_growth import GROWTH_VERSION, GrowthStrategy
from src.db.models_learning import LEARNING_VERSION, PostTypePerformance
from src.db.models_normalization import NormalizedPost, SourceType
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus
from src.services.intelligence.growth import plain_label
from src.services.metrics.merchant_metrics import compute_merchant_metrics
from src.logger import get_logger
from src.services.planning.calendar import seed_sale_events, upcoming_events

# Minimum recent-window sample size before a merchant's performance signal is
# treated as evidence-backed rather than a low-sample guess.
_MIN_PERFORMANCE_SAMPLES = 3
# Discount applied to a low-sample merchant's blended score (still surfaced,
# just not weighted as if it were evidence-backed).
_LOW_SAMPLE_DISCOUNT = 0.7
# Cap on performance_index (multiples of the cross-merchant median views/day)
# so one viral outlier post doesn't dominate the merchant mix.
_PERFORMANCE_INDEX_CAP = 3.0

logger = get_logger(__name__)

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
# posting-ramp multipliers by event type (research: channels 3–5x during GIF/BBD)
_RAMP = {"merchant_sale": 3.0, "festival": 2.5, "shopping": 2.0}


class CampaignPlanningEngine(BaseCollector):
    name = "campaign_planning"
    retryable = False

    def __init__(self, event_lead_days: int = 30):
        self.event_lead_days = event_lead_days
        self.bus = get_event_bus()

    def run(self, job) -> CollectorResult:
        result = CollectorResult()
        now = datetime.now(timezone.utc)
        today = now.date()
        with session_scope() as s:
            if s.scalar(select(func.count()).select_from(SaleEvent)) == 0:
                seed_sale_events(s, today)

            strat = s.scalar(select(GrowthStrategy).where(
                GrowthStrategy.growth_version == GROWTH_VERSION))
            if strat is None:
                result.skipped_reason = "No growth strategy. Run `tgagent growth` first."
                return result
            blueprint = strat.blueprint or {}
            perf = {p.post_type: (p.avg_views_per_day or 0.0) for p in s.scalars(
                select(PostTypePerformance).where(
                    PostTypePerformance.learning_version == LEARNING_VERSION))}
            recent = self._recent_distribution(s, now)
            events = upcoming_events(s, today, within_days=self.event_lead_days)
            event_data = [{
                "key": e.key, "name": e.name, "merchant_key": e.merchant_key,
                "event_type": e.event_type, "next_date": e.next_date,
                "window_days": e.window_days, "date_confidence": e.date_confidence,
                "notes": e.notes, "days_away": (e.next_date - today).days,
            } for e in events]

            # build plans
            daily = self._daily_plan(s, now, blueprint, perf, recent, today, event_data)
            weekly = self._weekly_plan(blueprint, perf, today, event_data)
            evt = self._event_plan(event_data[0], blueprint, perf) if event_data else None

            # persist (replace this version's plans)
            s.query(CampaignPlan).filter(CampaignPlan.campaign_version == CAMPAIGN_VERSION).delete()
            s.flush()
            for plan in [daily, weekly] + ([evt] if evt else []):
                s.add(CampaignPlan(campaign_version=CAMPAIGN_VERSION, generated_at=now, **plan))
                result.added += 1

        self.bus.publish(Event(event_type=EventType.PLAN_GENERATED, entity_type="channel",
                               entity_id="owned", data={"plans": result.added}, job_id=job.id))
        logger.info("[campaign_planning] generated %d plan(s); %d upcoming event(s)",
                    result.added, len(event_data))
        return result

    # ------------------------------------------------------------------ #
    def _recent_distribution(self, s: Session, now: datetime) -> dict:
        cutoff = now - timedelta(days=45)
        merch = Counter()
        post_types = Counter()
        rows = s.execute(
            select(NormalizedPost.primary_merchant_key, NormalizedPost.is_multi_deal)
            .join(Post, Post.id == NormalizedPost.source_id)
            .where(NormalizedPost.source_type == SourceType.OWNED, Post.posted_at >= cutoff)
        ).all()
        total = 0
        for mkey, multi in rows:
            total += 1
            if mkey:
                merch[mkey] += 1
            pt = "loot_deal" if multi else "single_deal"
            post_types[pt] += 1
        return {"total": total, "merchants": merch, "post_types": post_types}

    def _allocate_posts(self, blueprint: dict, posts: int) -> list[dict]:
        """Distribute the daily post budget across deal-types, nudged by the Growth
        content-mix action (increase/maintain/decrease)."""
        mix = blueprint.get("content_mix") or []
        if not mix:
            return []
        weights = []
        for m in mix:
            base = m.get("current_share") or 0.0
            mult = {"increase": 1.4, "decrease": 0.6}.get(m.get("action"), 1.0)
            weights.append((m, max(base * mult, 0.01)))
        wsum = sum(w for _, w in weights) or 1.0
        out = []
        for m, w in weights:
            n = round(posts * w / wsum)
            if n <= 0:
                continue
            out.append({"deal_type": plain_label(m["post_type"]),
                        "post_type": m["post_type"], "target_posts": n,
                        "avg_views_per_day": m.get("avg_views_per_day")})
        return out

    def _merchant_allocation(self, s: Session, recent: dict, now: datetime) -> list[dict]:
        """Blend recency-share with an age-normalized performance signal (avg
        views/day over the last 45 days) so the mix isn't just an echo of
        whichever merchant happened to post most recently. A merchant with
        fewer than `_MIN_PERFORMANCE_SAMPLES` posts in that window has its
        `performance_index` treated as low-confidence: it's still reported,
        but the blended score is discounted and `basis` says so explicitly."""
        merch = recent["merchants"]
        known_total = sum(merch.values()) or 1
        if not merch:
            return []

        metrics = compute_merchant_metrics(s)
        candidates = merch.most_common(6)

        windows: dict[str, dict] = {}
        for m, _c in candidates:
            mm = metrics.get(m)
            windows[m] = mm.window_summary(now, 45) if mm is not None else {
                "avg_views_per_day": None, "post_count": 0,
            }

        # Baseline for the performance index = median avg-views/day across
        # these merchants (not any one merchant's own number), so the index
        # reads as "N x the typical merchant" rather than a self-referential
        # ratio a single merchant could trivially maximize.
        vpds = [w["avg_views_per_day"] for w in windows.values() if w["avg_views_per_day"]]
        baseline = statistics.median(vpds) if vpds else None

        out = []
        for m, c in candidates:
            recent_share = round(c / known_total, 3)
            w = windows[m]
            avg_vpd = w["avg_views_per_day"]
            sample_size = w["post_count"] or 0
            performance_index = (
                round(min(avg_vpd / baseline, _PERFORMANCE_INDEX_CAP), 3)
                if avg_vpd and baseline else None
            )
            low_sample = sample_size < _MIN_PERFORMANCE_SAMPLES
            basis = "recency-only (low sample)" if low_sample else "recency+performance"

            # Blend: half recency-share, half performance-index (normalized to
            # the same 0..1-ish scale via the cap); missing performance data
            # falls back to a neutral 1.0x so it doesn't zero out the score.
            perf_component = performance_index if performance_index is not None else 1.0
            score = 0.5 * recent_share + 0.5 * (perf_component / _PERFORMANCE_INDEX_CAP)
            if low_sample:
                score *= _LOW_SAMPLE_DISCOUNT

            out.append({
                "merchant": m,
                "recent_share": recent_share,
                "avg_views_per_day": round(avg_vpd, 1) if avg_vpd is not None else None,
                "performance_index": performance_index,
                "sample_size": sample_size,
                "basis": basis,
                "score": round(score, 4),
            })
        out.sort(key=lambda x: x["score"], reverse=True)
        return out

    def _risks(self, recent: dict, posts_per_day: float) -> list[dict]:
        risks = []
        merch = recent["merchants"]
        known = sum(merch.values())
        if known >= 10:
            top_m, top_c = merch.most_common(1)[0]
            if top_c / known > 0.6:
                risks.append({"kind": "merchant_overuse",
                              "detail": f"{top_m} is {round(100*top_c/known)}% of recent "
                                        "merchant-attributed posts — diversify to avoid over-reliance."})
        post_types = recent["post_types"]
        ptotal = sum(post_types.values())
        if ptotal >= 10:
            top_pt, top_pc = post_types.most_common(1)[0]
            if top_pc / ptotal > 0.6:
                label = "loot / multi-deal posts" if top_pt == "loot_deal" else "single deal posts"
                risks.append({"kind": "content_concentration",
                              "detail": f"{label} is {round(100*top_pc/ptotal)}% of "
                                        "recent posts — add variety to reduce audience fatigue."})
        return risks

    def _expected_outcome(self, allocation: list[dict], perf: dict) -> dict:
        # rough daily reach estimate = sum(posts_for_type * that type's avg views/day)
        est = 0.0
        for a in allocation:
            vpd = perf.get(a["post_type"]) or 0.0
            est += a["target_posts"] * vpd
        return {"estimated_daily_views": round(est),
                "basis": "target posts per deal-type × that type's age-normalized views/day",
                "caveat": "estimate; sharpens as per-post velocity data accrues"}

    def _daily_plan(self, s: Session, now: datetime, blueprint, perf, recent, today, events) -> dict:
        posts = int(round(blueprint.get("posting_frequency_baseline") or 8))
        allocation = self._allocate_posts(blueprint, posts)
        schedule = blueprint.get("posting_plan") or []
        merchants = self._merchant_allocation(s, recent, now)
        risks = self._risks(recent, posts)
        near = events[0] if events and events[0]["days_away"] <= 7 else None
        bp = {
            "posts_planned": posts,
            "posting_windows": [{"part": p["part"], "hours": p["hours"],
                                 "posts": p["recommended_posts_per_day"],
                                 "sample_size": p.get("sample_size")} for p in schedule],
            "posting_windows_sample_size": blueprint.get("posting_plan_sample_size"),
            "deal_type_allocation": allocation,
            "merchant_allocation": merchants,
            "emoji_strategy": blueprint.get("emoji_strategy"),
            "event_note": (f"{near['name']} is {near['days_away']} day(s) away — consider ramping "
                           "frequency (see event plan)." if near else None),
        }
        conf = round(min(1.0, recent["total"] / 100), 3)
        return {"plan_type": PlanType.DAILY, "title": f"Daily plan — {today.isoformat()}",
                "target_date": today, "blueprint": bp, "risks": risks or None,
                "expected_outcome": self._expected_outcome(allocation, perf),
                "evidence": {"growth_version": GROWTH_VERSION, "recent_posts_45d": recent["total"]},
                "confidence": conf}

    def _weekly_plan(self, blueprint, perf, today, events) -> dict:
        posts = int(round(blueprint.get("posting_frequency_baseline") or 8))
        mix = [m for m in (blueprint.get("content_mix") or [])]
        # rotate top deal-types across the week for variety (diversity target)
        ordered = sorted(mix, key=lambda m: (m.get("avg_views_per_day") or 0), reverse=True)
        top_types = [plain_label(m["post_type"]) for m in ordered[:4]] or ["mixed deals"]
        days = []
        for i in range(7):
            d = today + timedelta(days=i)
            theme = top_types[i % len(top_types)]
            days.append({"day": WEEKDAYS[d.weekday()], "date": d.isoformat(),
                         "theme_focus": theme, "posts_planned": posts})
        evs = [{"name": e["name"], "date": e["next_date"].isoformat(),
                "days_away": e["days_away"], "date_confidence": e["date_confidence"]}
               for e in events[:3]]
        bp = {"posts_per_day": posts, "posts_per_week": posts * 7,
              "daily_themes": days, "rotation_for_diversity": top_types,
              "upcoming_events": evs}
        return {"plan_type": PlanType.WEEKLY,
                "title": f"Weekly plan — week of {today.isoformat()}",
                "target_date": today, "end_date": today + timedelta(days=6),
                "blueprint": bp, "risks": None,
                "expected_outcome": {"note": "Weekly reach scales ~7x the daily estimate; "
                                             "diversity rotation protects against fatigue."},
                "evidence": {"growth_version": GROWTH_VERSION}, "confidence": 0.6}

    def _event_plan(self, e: dict, blueprint, perf) -> dict:
        base = int(round(blueprint.get("posting_frequency_baseline") or 8))
        ramp = _RAMP.get(e["event_type"], 1.5)
        ramp_posts = int(round(base * ramp))
        approx = e["date_confidence"] == DateConfidence.APPROXIMATE
        merchant_focus = e["merchant_key"] or "diversify across top merchants"
        bp = {
            "event": e["name"], "event_date": e["next_date"].isoformat(),
            "days_away": e["days_away"], "window_days": e["window_days"],
            "date_confidence": e["date_confidence"],
            "recommended_posts_per_day_during_event": ramp_posts,
            "baseline_posts_per_day": base,
            "ramp_multiplier": ramp,
            "merchant_focus": merchant_focus,
            "prep_checklist": [
                f"Confirm exact {e['name']} dates" + (" (currently approximate)" if approx else ""),
                "Pre-stage top deal-types (loot / multi-link collections)",
                f"Prioritise {merchant_focus} inventory",
                "Increase posting cadence for the event window",
            ],
            "notes": e["notes"],
        }
        conf = round((0.7 if not approx else 0.5), 3)
        return {"plan_type": PlanType.EVENT,
                "title": f"Event campaign — {e['name']} (~{e['days_away']}d away)",
                "target_date": e["next_date"],
                "end_date": e["next_date"] + timedelta(days=e["window_days"]),
                "blueprint": bp,
                "risks": [{"kind": "date_uncertainty", "detail": "Exact dates announced near the "
                           "event; confirm before committing the schedule."}] if approx else None,
                "expected_outcome": {"note": f"Event windows historically drive {ramp:.0f}x normal "
                                             "volume and elevated reach across Indian deal channels."},
                "evidence": {"event_key": e["key"], "growth_version": GROWTH_VERSION},
                "confidence": conf}
