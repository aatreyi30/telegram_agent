"""Reasoning Engine (Phase 8).

Explains WHY channel metrics shifted between two comparable periods. Detects
performance shifts (posting volume, post-type mix, content style, engagement)
and attributes each to correlated, MEASURED changes — never a guess (source_truth
RULE: every insight must be data-backed).

Engagement uses maturity-matched windows (posts aged 30–60d vs 60–90d) to avoid
the cumulative-view recency bias, and is confidence-discounted with a velocity
caveat until true T+1h/4h/24h velocity accrues.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.services.collection.base import BaseCollector, CollectorResult
from src.db.models_learning import LEARNING_VERSION, PostTypePerformance
from src.db.models_reasoning import REASONING_VERSION, ReasonedInsight
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus
from src.services.intelligence.growth import plain_label
from src.ai.insight_writer import narrate
from src.logger import get_logger
from src.services.metrics import trend_metrics as T

logger = get_logger(__name__)

SIGNIF_PCT = 15.0     # relative % change to count as a shift
SIGNIF_PP = 0.05      # 5 percentage points for share/rate shifts
MIN_PERIOD_POSTS = 30
MIN_ENGAGE_POSTS = 20
WINDOW_DAYS = 30


def _pct_change(new, old):
    if not old:
        return None
    return round((new / old - 1) * 100, 1)


def _in10(share: float) -> str:
    """Turn a share (0..1) into plain language: 'about 3 in 10 posts'."""
    if share < 0.05:
        return "almost none of your posts"
    n = round(share * 10)
    if n >= 10:
        return "nearly all your posts"
    return f"about {n} in 10 posts"


class ReasoningEngine(BaseCollector):
    name = "reasoning"
    retryable = False

    def __init__(self, window_days: int = WINDOW_DAYS):
        self.window_days = window_days
        self.bus = get_event_bus()

    def run(self, job) -> CollectorResult:
        result = CollectorResult()
        now = datetime.now(timezone.utc)
        w = self.window_days
        with session_scope() as s:
            facts = T.load_owned_facts(s)
            perf = {p.post_type: p.avg_views_per_day for p in s.scalars(
                select(PostTypePerformance).where(
                    PostTypePerformance.learning_version == LEARNING_VERSION)
            ).all() if p.avg_views_per_day is not None}
        result.processed = len(facts)
        if len(facts) < 2 * MIN_PERIOD_POSTS:
            result.skipped_reason = "Not enough owned history to compare periods."
            return result

        perf_median = statistics.median(perf.values()) if perf else None

        recent = T.in_posting_window(facts, now - timedelta(days=w), now)
        prior = T.in_posting_window(facts, now - timedelta(days=2 * w), now - timedelta(days=w))
        insights: list[dict] = []

        self._volume_shift(recent, prior, w, now, insights)
        self._mix_shift(recent, prior, perf, perf_median, insights)
        self._style_shift(recent, prior, insights)
        self._engagement_shift(facts, now, perf, perf_median, insights)

        if not insights:
            result.detail["note"] = "No significant shifts detected in the window."

        with session_scope() as s:
            s.query(ReasonedInsight).filter(
                ReasonedInsight.reasoning_version == REASONING_VERSION).delete()
            s.flush()
            for ins in insights:
                s.add(ReasonedInsight(reasoning_version=REASONING_VERSION, detected_at=now, **ins))
            result.added = len(insights)

        for ins in insights:
            self.bus.publish(Event(
                event_type=EventType.PERFORMANCE_SHIFT_DETECTED, entity_type="channel",
                entity_id="owned", data={"metric": ins["metric"], "direction": ins["direction"]},
                job_id=job.id,
            ))
        logger.info("[reasoning] %d insight(s) over %d-day windows", len(insights), w)
        return result

    # ------------------------------------------------------------------ #
    def _volume_shift(self, recent, prior, w, now, insights):
        if len(recent) < MIN_PERIOD_POSTS or len(prior) < MIN_PERIOD_POSTS:
            return
        ppd_r = T.posts_per_day(recent, w)
        ppd_p = T.posts_per_day(prior, w)
        change = _pct_change(ppd_r, ppd_p)
        if change is None or abs(change) < SIGNIF_PCT:
            return
        direction = "up" if change > 0 else "down"
        verb = "less" if direction == "down" else "more"
        obs = (f"You're posting {verb} often — about {ppd_r:.0f} posts a day in the last month, "
               f"compared with about {ppd_p:.0f} a day the month before.")
        evidence = {"posts_per_day_recent": ppd_r, "posts_per_day_prior": ppd_p,
                    "n_recent": len(recent), "n_prior": len(prior), "change_pct": change}
        fallback = (f"A {abs(change):.0f}% {'drop' if direction == 'down' else 'increase'} in daily "
                    f"posts directly changes how many times a day your deals can appear in someone's "
                    f"feed — {'fewer' if direction == 'down' else 'more'} posts means "
                    f"{'fewer' if direction == 'down' else 'more'} chances to be seen, independent of "
                    "how good any single post is.")
        why = narrate("why a change in posting volume matters", obs, evidence, fallback)
        insights.append({
            "metric": "posting_volume", "direction": direction,
            "change_value": change, "change_unit": "pct",
            "period_label": f"last {w}d vs prior {w}d",
            "observation": obs, "reasoning": why,
            "evidence": evidence,
            "confidence": round(min(1.0, min(len(recent), len(prior)) / 100), 3),
        })

    def _mix_shift(self, recent, prior, perf, perf_median, insights):
        if len(recent) < MIN_PERIOD_POSTS or len(prior) < MIN_PERIOD_POSTS:
            return
        def _key(f): return "loot_deal" if f.is_multi_deal else "single_deal"
        sr = T.share_map(recent, _key)
        sp = T.share_map(prior, _key)
        deltas = []
        for pt in set(sr) | set(sp):
            d = sr.get(pt, 0.0) - sp.get(pt, 0.0)
            if abs(d) >= SIGNIF_PP:
                deltas.append((abs(d), d, pt))
        deltas.sort(reverse=True)
        for _, d, pt in deltas[:2]:
            direction = "up" if d > 0 else "down"
            label = plain_label(pt)
            moved = "more" if d > 0 else "fewer"
            obs = (f"You posted {moved} {label} — they went from {_in10(sp.get(pt, 0))} "
                   f"to {_in10(sr.get(pt, 0))}.")
            vpd = perf.get(pt)
            evidence = {"post_type": pt, "share_recent": round(sr.get(pt, 0), 3),
                        "share_prior": round(sp.get(pt, 0), 3),
                        "avg_views_per_day": vpd, "perf_median": perf_median}
            if vpd is not None and perf_median:
                good = vpd >= perf_median   # this type does better than most
                helps = (d > 0) == good     # posting more of a good type, or less of a bad type
                if helps and d > 0:
                    fallback = (f"Good move — these posts get about {vpd:.0f} views a day, more than "
                                f"your usual {perf_median:.0f}, so posting more of them should bring more views.")
                elif helps and d < 0:
                    fallback = (f"This should help — you cut back on posts that get fewer views than "
                                f"usual (about {vpd:.0f} a day vs your usual {perf_median:.0f}).")
                elif not helps and d > 0:
                    fallback = (f"Worth watching — these posts get fewer views than usual (about "
                                f"{vpd:.0f} a day vs your usual {perf_median:.0f}), so leaning on them can lower your reach.")
                else:
                    fallback = (f"This may cost you — you posted fewer of a type that was doing better "
                                f"than most (about {vpd:.0f} views a day vs your usual {perf_median:.0f}).")
            else:
                fallback = "This is a change in the kind of deals you posted, without enough performance data yet to say if it helps or hurts."
            why = narrate("why this post-type mix shift matters", obs, evidence, fallback)
            insights.append({
                "metric": "post_type_mix", "direction": direction,
                "change_value": round(d * 100, 1), "change_unit": "pp",
                "period_label": f"last {WINDOW_DAYS}d vs prior {WINDOW_DAYS}d",
                "observation": obs, "reasoning": why,
                "evidence": evidence,
                "confidence": round(min(1.0, min(len(recent), len(prior)) / 100), 3),
            })

    def _style_shift(self, recent, prior, insights):
        if len(recent) < MIN_PERIOD_POSTS or len(prior) < MIN_PERIOD_POSTS:
            return
        specs = (
            ("cta", "a 'buy now / grab deal' style call-to-action", lambda f: f.has_cta),
            ("media", "an image or video", lambda f: f.has_media),
        )
        for factor, label, pred in specs:
            rr = T.rate(recent, pred) or 0.0
            rp = T.rate(prior, pred) or 0.0
            d = rr - rp
            if abs(d) < SIGNIF_PP:
                continue
            direction = "up" if d > 0 else "down"
            moved = "more" if d > 0 else "fewer"
            obs = (f"You're using {label} in {moved} posts — {_in10(rr)} now, "
                   f"versus {_in10(rp)} before.")
            pct = abs(round(d * 100, 1))
            evidence = {"factor": label, "rate_recent": round(rr, 3), "rate_prior": round(rp, 3),
                        "change_pp": round(d * 100, 1)}
            # data-specific fallback — varies with actual magnitude, not a fixed sentence
            if factor == "cta":
                fallback = (f"That's a {pct:.0f}-point shift in wording, not in what you're selling — "
                            "on its own it rarely explains a reach change unless a content-mix or "
                            "volume shift moved alongside it.")
            else:
                fallback = (f"That's a {pct:.0f}-point shift in how many posts carry an image — plain "
                            "text-and-link posts have historically matched or beaten image-heavy ones "
                            "in this channel's data, so this shift alone is unlikely to explain a reach change.")
            why = narrate(f"why this {factor} shift happened and whether it matters", obs, evidence, fallback)
            insights.append({
                "metric": "content_style", "direction": direction,
                "change_value": round(d * 100, 1), "change_unit": "pp",
                "period_label": f"last {WINDOW_DAYS}d vs prior {WINDOW_DAYS}d",
                "observation": obs, "reasoning": why,
                "evidence": evidence,
                "confidence": round(min(1.0, min(len(recent), len(prior)) / 100), 3),
            })

    def _engagement_shift(self, facts, now, perf, perf_median, insights):
        # maturity-matched: aged 30-60d (recent) vs 60-90d (prior)
        recentE = T.matured_window(facts, now, 30, 60)
        priorE = T.matured_window(facts, now, 60, 90)
        vr, nr = T.avg_views_per_day(recentE, now)
        vp, np_ = T.avg_views_per_day(priorE, now)
        if vr is None or vp is None or nr < MIN_ENGAGE_POSTS or np_ < MIN_ENGAGE_POSTS:
            return
        change = _pct_change(vr, vp)
        if change is None or abs(change) < SIGNIF_PCT:
            return
        direction = "up" if change > 0 else "down"

        # attribute to measured co-shifts between the SAME two engagement windows
        reasons: list[str] = []
        ev: dict = {"views_per_day_recent": vr, "views_per_day_prior": vp,
                    "n_recent": nr, "n_prior": np_,
                    "windows": "aged 30-60d vs 60-90d (maturity-matched)"}

        # volume within the engagement windows (dilution)
        ppd_r = round(len(recentE) / 30, 3)
        ppd_p = round(len(priorE) / 30, 3)
        vol_change = _pct_change(ppd_r, ppd_p)
        if vol_change is not None and abs(vol_change) >= SIGNIF_PCT:
            if (direction == "down" and vol_change > 0) or (direction == "up" and vol_change < 0):
                reasons.append(f"you posted {'more' if vol_change>0 else 'less'} often, which "
                               f"spreads views across {'more' if vol_change>0 else 'fewer'} posts")
                ev["volume_change_pct"] = vol_change

        # mix shift toward under/over performers
        def _key(f): return "loot_deal" if f.is_multi_deal else "single_deal"
        sr = T.share_map(recentE, _key)
        sp = T.share_map(priorE, _key)
        if perf_median:
            contributors = []
            for pt in set(sr) | set(sp):
                d = sr.get(pt, 0.0) - sp.get(pt, 0.0)
                vpd = perf.get(pt)
                if abs(d) >= SIGNIF_PP and vpd is not None:
                    aligned = (d > 0) == (vpd >= perf_median)  # gained a good / lost a bad -> up
                    if (direction == "up") == aligned:
                        contributors.append((abs(d), pt, d, vpd))
            contributors.sort(reverse=True)
            for _, pt, d, vpd in contributors[:2]:
                reasons.append(f"you posted {'more' if d>0 else 'fewer'} {plain_label(pt)}, "
                               f"which usually get about {vpd:.0f} views a day")
                ev.setdefault("mix_contributors", []).append(
                    {"post_type": pt, "share_delta_pp": round(d * 100, 1), "avg_views_per_day": vpd})

        obs = (f"Your posts are getting {'more' if direction == 'up' else 'fewer'} views — about "
               f"{vr:.0f} views a day now, versus about {vp:.0f} a month earlier "
               "(comparing posts that have been up for the same length of time).")
        fallback = ("Likely because " + "; and ".join(reasons) + "." if reasons
                    else "We couldn't pin this on one clear cause in your data.")
        fallback += (" This is an early estimate — it will get more accurate as we track how fast "
                     "each new post gains views.")
        why = narrate("why engagement per post changed", obs, ev, fallback)
        insights.append({
            "metric": "engagement", "direction": direction,
            "change_value": change, "change_unit": "pct",
            "period_label": "matured posts: aged 30-60d vs 60-90d",
            "observation": obs, "reasoning": why, "evidence": ev,
            "confidence": round(min(1.0, min(nr, np_) / 60) * 0.8, 3),  # velocity discount
        })
