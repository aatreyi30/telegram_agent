"""Channel Learning Engine (Phase 6) implementation.

Consumes owned-channel history (engagement + Phase-2 normalized entities +
Phase-3 clusters) and produces a style profile, per-post-type performance, and
discrete evidence-backed learning records.

Honesty:
  * the per-post metric (``Fact.view_rate``) prefers TRUE first-24h velocity from
    the nearest ~T+24h PostMetricSnapshot — comparable across posts regardless of
    age — and only falls back to the cumulative views/age proxy for posts with no
    24h snapshot yet (older history); it sharpens toward pure velocity as snapshots
    accrue (Data Validation Matrix Feature 7/15);
  * comparative learnings require a minimum sample and carry confidence;
  * subscriber-growth-per-posttype and CTR are UNAVAILABLE and simply absent.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.services.collection.base import BaseCollector, CollectorResult
from src.db.models import Post, PostMetricSnapshot
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

IST = timezone(timedelta(hours=5, minutes=30))
MIN_GROUP_SAMPLE = 20        # min posts in a subgroup to emit a comparative learning
RELIABLE_HOUR_SAMPLE = 100   # min posts in an hour before a timing window is "proven"
FULL_CONFIDENCE_N = 50

# True first-24h velocity anchor: the nearest PostMetricSnapshot whose age_hours
# falls in [24 - tol, 24 + tol] wins. Mirrors analytics/engagement.py so the two
# read the same "views in the first day" quantity.
_VELOCITY_TARGET_HOURS = 24.0
_VELOCITY_TOLERANCE_HOURS = 2.0


@dataclass
class Fact:
    posted_at: datetime | None
    views: int | None
    forwards: int | None
    reactions: int | None
    text_len: int
    num_links: int
    has_coupon: bool
    is_multi_deal: bool
    has_cta: bool
    has_media: bool
    emojis: list
    hashtags: list
    cluster: str | None
    merchant_key: str | None
    views_24h: int | None = None   # nearest ~T+24h snapshot views (true velocity), if captured

    def views_per_day(self, now: datetime) -> float | None:
        if self.views is None or self.posted_at is None:
            return None
        pa = self.posted_at if self.posted_at.tzinfo else self.posted_at.replace(tzinfo=timezone.utc)
        age = max((now - pa).total_seconds() / 86400.0, 1.0)
        return self.views / age

    def view_rate(self, now: datetime) -> float | None:
        """The per-post engagement metric, best-available. Prefers TRUE first-24h
        velocity (``views_24h`` from the nearest ~T+24h snapshot) — comparable across
        posts regardless of age, so a fast-starting recent post isn't buried by an old
        post that merely accumulated views over weeks. Falls back to the cumulative
        views/age proxy for posts with no 24h snapshot yet (history predating snapshot
        collection). Both are per-day view rates, so they mix into one pool honestly;
        the dataset sharpens toward pure velocity as snapshots accrue."""
        if self.views_24h is not None:
            return float(self.views_24h)
        return self.views_per_day(now)


def _conf(n: int) -> float:
    return round(min(1.0, n / FULL_CONFIDENCE_N), 3)


def _mean(vals) -> float | None:
    return round(statistics.fmean(vals), 3) if vals else None


class ChannelLearningEngine(BaseCollector):
    name = "channel_learning"
    retryable = False

    def __init__(self) -> None:
        self.bus = get_event_bus()

    def run(self, job) -> CollectorResult:
        result = CollectorResult()
        now = datetime.now(timezone.utc)
        with session_scope() as s:
            facts = self._load(s)
        result.processed = len(facts)
        if len(facts) < MIN_GROUP_SAMPLE:
            result.skipped_reason = (
                f"Only {len(facts)} owned normalized posts — need >= {MIN_GROUP_SAMPLE} "
                "to learn reliably. Run collect-owned + normalize + classify first."
            )
            return result

        style = self._style_profile(facts, now)
        perf = self._post_type_performance(facts, now)
        records = self._learning_records(facts, now)

        with session_scope() as s:
            for model in (LearningRecord, PostTypePerformance, ChannelStyleProfile):
                s.query(model).filter(model.learning_version == LEARNING_VERSION).delete()
            s.flush()
            s.add(ChannelStyleProfile(**style))
            for row in perf:
                s.add(PostTypePerformance(**row))
            for rec in records:
                s.add(LearningRecord(**rec))
        result.added = 1 + len(perf) + len(records)

        self.bus.publish(Event(
            event_type=EventType.KNOWLEDGE_UPDATED, entity_type="channel",
            entity_id="owned", data={"records": len(records), "post_types": len(perf)},
            job_id=job.id,
        ))
        logger.info("[channel_learning] style + %d post-types + %d learnings",
                    len(perf), len(records))
        return result

    # ------------------------------------------------------------------ #
    def _load(self, s: Session) -> list[Fact]:
        np_rows = s.execute(
            select(
                NormalizedPost.source_id, NormalizedPost.num_links, NormalizedPost.has_coupon,
                NormalizedPost.is_multi_deal, NormalizedPost.emojis, NormalizedPost.hashtags,
                NormalizedPost.cta_texts, NormalizedPost.primary_merchant_key, NormalizedPost.id,
            ).where(NormalizedPost.source_type == SourceType.OWNED)
        ).all()
        from sqlalchemy import func
        post_meta = {
            pid: (posted_at, views, forwards, reactions, tlen, media)
            for pid, posted_at, views, forwards, reactions, tlen, media in s.execute(
                select(Post.id, Post.posted_at, Post.views, Post.forwards,
                       Post.reactions_total, func.length(Post.text), Post.has_media)
            ).all()
        }
        velocity = self._views_24h(s, list(post_meta.keys()))
        facts = []
        for src_id, num_links, has_coupon, multi, emojis, hashtags, cta, mkey, npid in np_rows:
            meta = post_meta.get(src_id)
            if not meta:
                continue
            posted_at, views, forwards, reactions, tlen, media = meta
            cluster = "loot_deal" if multi else "single_deal"
            facts.append(Fact(
                posted_at=posted_at, views=views, forwards=forwards, reactions=reactions,
                text_len=tlen or 0, num_links=num_links, has_coupon=has_coupon,
                is_multi_deal=multi, has_cta=bool(cta), has_media=bool(media),
                emojis=emojis or [], hashtags=hashtags or [], cluster=cluster,
                merchant_key=mkey, views_24h=velocity.get(src_id),
            ))
        return facts

    @staticmethod
    def _views_24h(s: Session, post_ids: list[int]) -> dict[int, int]:
        """Map post_id -> views at its nearest ~T+24h snapshot (true first-day
        velocity), for the posts that have one. Posts with no snapshot in the window
        are simply absent, and fall back to the cumulative proxy in ``Fact.view_rate``."""
        if not post_ids:
            return {}
        lo = _VELOCITY_TARGET_HOURS - _VELOCITY_TOLERANCE_HOURS
        hi = _VELOCITY_TARGET_HOURS + _VELOCITY_TOLERANCE_HOURS
        snaps = s.scalars(
            select(PostMetricSnapshot).where(
                PostMetricSnapshot.post_id.in_(post_ids),
                PostMetricSnapshot.age_hours.isnot(None),
                PostMetricSnapshot.age_hours.between(lo, hi),
                PostMetricSnapshot.views.isnot(None),
            )
        ).all()
        nearest: dict[int, PostMetricSnapshot] = {}
        for sn in snaps:
            cur = nearest.get(sn.post_id)
            if cur is None or abs(sn.age_hours - _VELOCITY_TARGET_HOURS) < abs(
                cur.age_hours - _VELOCITY_TARGET_HOURS
            ):
                nearest[sn.post_id] = sn
        return {pid: sn.views for pid, sn in nearest.items()}

    def _style_profile(self, facts: list[Fact], now: datetime) -> dict:
        n = len(facts)
        dated = [(f.posted_at if f.posted_at and f.posted_at.tzinfo else
                  (f.posted_at.replace(tzinfo=timezone.utc) if f.posted_at else None))
                 for f in facts]
        dated = [d for d in dated if d]
        span_days = (max((max(dated) - min(dated)).days, 0) + 1) if dated else None
        hours = Counter(d.astimezone(IST).hour for d in dated)
        weekdays = Counter(d.astimezone(IST).strftime("%a") for d in dated)
        active_weeks = len({(d.isocalendar().year, d.isocalendar().week) for d in dated}) if dated else 0
        span_weeks = max((span_days or 1) / 7.0, 1.0)
        emoji_counter = Counter()
        for f in facts:
            emoji_counter.update(f.emojis)
        return {
            "learning_version": LEARNING_VERSION,
            "computed_at": now,
            "post_count": n,
            "avg_caption_len": _mean([f.text_len for f in facts]),
            "median_caption_len": statistics.median([f.text_len for f in facts]) if facts else None,
            "avg_emojis": _mean([len(f.emojis) for f in facts]),
            "top_emojis": emoji_counter.most_common(10) or None,
            "hashtag_rate": _mean([1 if f.hashtags else 0 for f in facts]),
            "cta_rate": _mean([1 if f.has_cta else 0 for f in facts]),
            "coupon_rate": _mean([1 if f.has_coupon else 0 for f in facts]),
            "multi_deal_rate": _mean([1 if f.is_multi_deal else 0 for f in facts]),
            "avg_links": _mean([f.num_links for f in facts]),
            "media_rate": _mean([1 if f.has_media else 0 for f in facts]),
            "posts_per_day": round(n / span_days, 3) if span_days else None,
            "posts_per_week": round(n / span_weeks, 3),
            "top_hours_ist": hours.most_common(5) or None,
            "top_weekdays": weekdays.most_common(7) or None,
            "posting_consistency": round(min(active_weeks / span_weeks, 1.0), 3) if span_weeks else None,
            "confidence": _conf(n),
        }

    def _post_type_performance(self, facts: list[Fact], now: datetime) -> list[dict]:
        groups: dict[str, list[Fact]] = defaultdict(list)
        for f in facts:
            if f.cluster:
                groups[f.cluster].append(f)
        rows = []
        for cluster, fs in groups.items():
            vpd = [f.view_rate(now) for f in fs if f.view_rate(now) is not None]
            rows.append({
                "learning_version": LEARNING_VERSION,
                "post_type": cluster,
                "post_count": len(fs),
                "share": round(len(fs) / len(facts), 3),
                "avg_views": _mean([f.views for f in fs if f.views is not None]),
                "avg_views_per_day": _mean(vpd),
                "avg_forwards": _mean([f.forwards for f in fs if f.forwards is not None]),
                "avg_reactions": _mean([f.reactions for f in fs if f.reactions is not None]),
                "confidence": _conf(len(fs)),
                "computed_at": now,
            })
        rows.sort(key=lambda r: (r["avg_views_per_day"] or -1), reverse=True)
        for i, r in enumerate(rows):
            r["rank_by_views_per_day"] = i + 1
        return rows

    def _learning_records(self, facts: list[Fact], now: datetime) -> list[dict]:
        recs: list[dict] = []
        baseline = _mean([f.view_rate(now) for f in facts if f.view_rate(now) is not None])
        if not baseline:
            return recs

        def add(category, statement, metric, value, sample, evidence):
            recs.append({
                "learning_version": LEARNING_VERSION, "category": category,
                "statement": statement, "metric_name": metric, "metric_value": value,
                "comparison_value": baseline, "sample_size": sample,
                "confidence": _conf(sample), "evidence": evidence, "recorded_at": now,
            })

        def subgroup_vpd(pred) -> tuple[float | None, int]:
            vals = [f.view_rate(now) for f in facts if pred(f) and f.view_rate(now) is not None]
            return (_mean(vals), len(vals))

        def lift_pct(v):
            return round((v / baseline - 1) * 100, 1)

        # (1) best & worst post types (age-normalized) vs channel baseline
        perf = self._post_type_performance(facts, now)
        eligible = [p for p in perf if p["post_count"] >= MIN_GROUP_SAMPLE and p["avg_views_per_day"]]
        if eligible:
            best = eligible[0]
            add("post_type", f"Post type '{best['post_type']}' is your top performer "
                f"({lift_pct(best['avg_views_per_day'])}% vs channel avg views/day).",
                "avg_views_per_day", best["avg_views_per_day"], best["post_count"],
                {"post_type": best["post_type"], "baseline_views_per_day": baseline})
            worst = eligible[-1]
            if worst["post_type"] != best["post_type"]:
                add("post_type", f"Post type '{worst['post_type']}' underperforms "
                    f"({lift_pct(worst['avg_views_per_day'])}% vs channel avg).",
                    "avg_views_per_day", worst["avg_views_per_day"], worst["post_count"],
                    {"post_type": worst["post_type"], "baseline_views_per_day": baseline})

        # (2) CTA effect
        with_cta, n_cta = subgroup_vpd(lambda f: f.has_cta)
        without_cta, n_no = subgroup_vpd(lambda f: not f.has_cta)
        if with_cta and without_cta and n_cta >= MIN_GROUP_SAMPLE and n_no >= MIN_GROUP_SAMPLE:
            diff = round((with_cta / without_cta - 1) * 100, 1)
            add("cta", f"Posts with a call-to-action get {diff}% "
                f"{'more' if diff >= 0 else 'less'} views/day than those without.",
                "avg_views_per_day", with_cta, n_cta,
                {"with_cta": with_cta, "without_cta": without_cta, "n_with": n_cta, "n_without": n_no})

        # (3) media effect
        with_m, n_m = subgroup_vpd(lambda f: f.has_media)
        without_m, n_nm = subgroup_vpd(lambda f: not f.has_media)
        if with_m and without_m and n_m >= MIN_GROUP_SAMPLE and n_nm >= MIN_GROUP_SAMPLE:
            diff = round((with_m / without_m - 1) * 100, 1)
            add("media", f"Posts with media get {diff}% "
                f"{'more' if diff >= 0 else 'less'} views/day than text-only.",
                "avg_views_per_day", with_m, n_m,
                {"with_media": with_m, "without_media": without_m, "n_with": n_m, "n_without": n_nm})

        # (4) emoji effect (top emojis only; data-derived, never hardcoded)
        emoji_counter = Counter()
        for f in facts:
            emoji_counter.update(set(f.emojis))
        for emoji, cnt in emoji_counter.most_common(6):
            if cnt < MIN_GROUP_SAMPLE:
                continue
            v, n = subgroup_vpd(lambda f, e=emoji: e in f.emojis)
            if v:
                add("emoji", f"Posts using {emoji} get {lift_pct(v)}% vs channel avg "
                    "views/day (correlation, not proven cause — {} tends to appear in your best-performing "
                    "post types).".format(emoji),
                    "avg_views_per_day", v, n, {"emoji": emoji, "baseline_views_per_day": baseline,
                                                "note": "correlational, not causal"})

        # (5) posting windows (IST) — sample-aware: a single "best hour" from a
        # handful of posts is noise. Separate RELIABLE windows (large sample) from
        # HIGH-AVG-but-small-sample windows, and expose the full ranking as evidence.
        hour_vals: dict[int, list[float]] = defaultdict(list)
        for f in facts:
            vpd = f.view_rate(now)
            if vpd is not None and f.posted_at:
                pa = f.posted_at if f.posted_at.tzinfo else f.posted_at.replace(tzinfo=timezone.utc)
                hour_vals[pa.astimezone(IST).hour].append(vpd)
        hour_stats = {h: (_mean(v), len(v)) for h, v in hour_vals.items() if v}
        reliable = {h: st for h, st in hour_stats.items() if st[1] >= RELIABLE_HOUR_SAMPLE}
        small = {h: st for h, st in hour_stats.items()
                 if MIN_GROUP_SAMPLE <= st[1] < RELIABLE_HOUR_SAMPLE}
        if reliable:
            ranked = sorted(reliable.items(), key=lambda kv: kv[1][0] or 0, reverse=True)
            top = ranked[:3]
            small_ranked = sorted(small.items(), key=lambda kv: kv[1][0] or 0, reverse=True)[:3]
            win_txt = "; ".join(
                f"{h:02d}:00 IST ({avg:.1f} views/day, n={n}, {lift_pct(avg):+.0f}% vs avg)"
                for h, (avg, n) in top
            )
            stmt = f"Your strongest proven posting windows (IST) are: {win_txt}."
            if small_ranked:
                exp = ", ".join(f"{h:02d}:00" for h, _ in small_ranked)
                stmt += (f" Late/low-volume hours ({exp}) show higher per-post views but on "
                         f"small samples (n<{RELIABLE_HOUR_SAMPLE}) — treat as experiments, not proven.")
            stmt += (" Note: uses each post's first-24h view velocity where a T+24h "
                     "snapshot exists, else a cumulative-view proxy; sharpens as more "
                     "24h snapshots accrue.")
            add("timing", stmt, "avg_views_per_day", top[0][1][0], top[0][1][1], {
                "reliable_windows": [[h, round(avg, 1), n, round(lift_pct(avg), 1)] for h, (avg, n) in top],
                "experimental_windows": [[h, round(avg, 1), n] for h, (avg, n) in small_ranked],
                # full per-hour table (hour, avg_views_per_day, n_posts) so the Growth
                # Engine can build a realistic all-day posting schedule, not single hours.
                "hourly_all": [[h, round(st[0], 1), st[1]] for h, st in sorted(hour_stats.items())],
                "reliable_sample_threshold": RELIABLE_HOUR_SAMPLE,
                "baseline_views_per_day": round(baseline, 2),
            })

        # (6) best merchant (known merchants only)
        merch_vals: dict[str, list[float]] = defaultdict(list)
        for f in facts:
            vpd = f.view_rate(now)
            if f.merchant_key and vpd is not None:
                merch_vals[f.merchant_key].append(vpd)
        merch_avgs = {m: (_mean(v), len(v)) for m, v in merch_vals.items() if len(v) >= MIN_GROUP_SAMPLE}
        # A merchant recommendation only makes sense when we can COMPARE merchants.
        # With <2 resolved merchants (most links are unresolved shortlinks) there is
        # no valid comparison, so we withhold it rather than crown the only one —
        # especially since it may underperform the channel average.
        if len(merch_avgs) >= 2:
            best_m = max(merch_avgs.items(), key=lambda kv: kv[1][0] or 0)
            if best_m[1][0] and best_m[1][0] > baseline:  # only if it actually outperforms
                add("merchant", f"Among resolved merchants, '{best_m[0]}' posts perform best at "
                    f"{best_m[1][0]:.0f} views/day ({lift_pct(best_m[1][0])}% vs your {baseline:.0f} "
                    f"channel average), over {best_m[1][1]} posts.",
                    "avg_views_per_day", best_m[1][0], best_m[1][1],
                    {"merchant": best_m[0], "baseline_views_per_day": round(baseline, 1),
                     "resolved_merchants_compared": len(merch_avgs),
                     "note": "resolved merchants only; most links are unresolved shortlinks"})

        return recs
