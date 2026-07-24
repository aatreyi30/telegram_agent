"""Grounding-context gatherer.

Pulls the latest VERIFIED outputs from the deterministic engines into plain dicts
that are handed to Claude as the only permitted source of truth. Each getter is a
read-only query; nothing here calls an LLM.
"""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import Channel
from src.db.models_growth import GROWTH_VERSION, GrowthRecommendation, GrowthStrategy
from src.db.models_intelligence import (
    MERCHANT_INTEL_VERSION,
    MerchantOpportunity,
    MerchantProfile,
)
from src.db.models_learning import (
    LEARNING_VERSION,
    ChannelStyleProfile,
    LearningRecord,
    PostTypePerformance,
)
from src.db.models_normalization import NormalizedPost, SourceType
from src.db.models_reasoning import REASONING_VERSION, ReasonedInsight


def channel_overview(s: Session) -> dict:
    ch = s.scalars(select(Channel).order_by(Channel.participants_count.desc())).first()
    if not ch:
        return {"available": False}
    return {"available": True, "title": ch.title, "username": ch.username,
            "subscribers": ch.participants_count}


def _owned_window_desc(s: Session) -> str:
    from src.services.analytics.periods import owned_window
    w = owned_window(s)
    return f"owned, last {w['months']} mo"


def reasoning_insights(s: Session) -> list[dict]:
    return [{"metric": i.metric, "direction": i.direction,
             "change": i.change_value, "unit": i.change_unit,
             "observation": i.observation, "why": i.reasoning,
             "period": i.period_label, "evidence": i.evidence,
             "confidence": i.confidence}
            for i in s.scalars(select(ReasonedInsight).where(
                ReasonedInsight.reasoning_version == REASONING_VERSION)
                .order_by(ReasonedInsight.confidence.desc()))]


def growth_recommendations(s: Session, limit: int = 8) -> list[dict]:
    return [{"priority": r.priority, "category": r.category,
             "recommendation": r.recommendation, "reasoning": r.reasoning,
             "evidence": r.evidence, "confidence": r.confidence,
             "expected_outcome": r.expected_outcome}
            for r in s.scalars(select(GrowthRecommendation)
                .where(GrowthRecommendation.growth_version == GROWTH_VERSION)
                .order_by(GrowthRecommendation.priority).limit(limit))]


def growth_blueprint(s: Session) -> dict:
    strat = s.scalar(select(GrowthStrategy).where(
        GrowthStrategy.growth_version == GROWTH_VERSION))
    if not strat:
        return {"available": False}
    return {"available": True, "mode": strat.mode, "channel_type": strat.channel_type,
            "blueprint": strat.blueprint, "confidence": strat.confidence}


def post_type_performance(s: Session) -> list[dict]:
    return [{"post_type": p.post_type, "posts": p.post_count, "share": p.share,
             "avg_views_per_day": p.avg_views_per_day, "rank": p.rank_by_views_per_day}
            for p in s.scalars(select(PostTypePerformance)
                .where(PostTypePerformance.learning_version == LEARNING_VERSION)
                .order_by(PostTypePerformance.rank_by_views_per_day))]


def post_type_performance_range(s: Session, start, end) -> list[dict]:
    """Same shape as `post_type_performance`, computed live from raw owned posts
    within [start, end) instead of the last batch snapshot — lets the Insights
    date-picker show performance for the selected window rather than always
    whatever the last Channel Learning Engine run happened to cover."""
    import statistics
    from collections import defaultdict
    from datetime import datetime, timezone

    from src.db.models import Post
    from src.db.models_normalization import NormalizedPost, SourceType

    q = (
        select(Post.posted_at, Post.views, NormalizedPost.is_multi_deal)
        .select_from(Post)
        .join(NormalizedPost, (NormalizedPost.source_id == Post.id)
              & (NormalizedPost.source_type == SourceType.OWNED))
    )
    if start:
        q = q.where(Post.posted_at >= start)
    if end:
        q = q.where(Post.posted_at < end)

    def _type(is_multi: bool) -> str:
        return "loot_deal" if is_multi else "single_deal"

    now = datetime.now(timezone.utc)
    groups: dict[str, list[tuple]] = defaultdict(list)
    for posted_at, views, is_multi in s.execute(q).all():
        groups[_type(is_multi)].append((posted_at, views))

    total = sum(len(items) for items in groups.values())
    if not total:
        return []

    out = []
    for descriptor, items in groups.items():
        vpd = []
        for posted_at, views in items:
            if views is None or posted_at is None:
                continue
            pa = posted_at if posted_at.tzinfo else posted_at.replace(tzinfo=timezone.utc)
            age = max((now - pa).total_seconds() / 86400.0, 1.0)
            vpd.append(views / age)
        out.append({
            "post_type": descriptor, "posts": len(items),
            "share": round(len(items) / total, 3),
            "avg_views_per_day": round(statistics.fmean(vpd), 1) if vpd else None,
        })
    out.sort(key=lambda r: (r["avg_views_per_day"] or -1), reverse=True)
    for i, r in enumerate(out):
        r["rank"] = i + 1
    return out


def learnings(s: Session) -> list[dict]:
    window = _owned_window_desc(s)
    out = []
    for r in s.scalars(select(LearningRecord)
            .where(LearningRecord.learning_version == LEARNING_VERSION)
            .order_by(LearningRecord.confidence.desc())):
        how = None
        if r.metric_value is not None and r.comparison_value:
            lift = (r.metric_value / r.comparison_value - 1) * 100
            how = (f"{r.metric_value:.1f} vs {r.comparison_value:.1f} {r.metric_name or 'views/day'} "
                   f"= {lift:+.0f}% · n={r.sample_size:,} · {window}")
        out.append({"category": r.category, "statement": r.statement,
                    "confidence": r.confidence, "sample_size": r.sample_size,
                    "how_calculated": how, "period": window})
    return out


def channel_style(s: Session) -> dict:
    st = s.scalar(select(ChannelStyleProfile).where(
        ChannelStyleProfile.learning_version == LEARNING_VERSION))
    if not st:
        return {"available": False}
    return {"available": True, "avg_caption_len": st.avg_caption_len,
            "top_emojis": st.top_emojis, "cta_rate": st.cta_rate,
            "coupon_rate": st.coupon_rate, "multi_deal_rate": st.multi_deal_rate,
            "media_rate": st.media_rate, "posts_per_day": st.posts_per_day,
            "top_hours_ist": st.top_hours_ist}


def merchant_profiles(s: Session) -> list[dict]:
    return [{"merchant": p.merchant_key, "posts": p.post_count_owned,
             "avg_views_per_day": p.avg_views_per_day, "price_median": p.price_median,
             "price_sample_size": p.price_sample_size, "confidence": p.confidence}
            for p in s.scalars(select(MerchantProfile)
                .where(MerchantProfile.intel_version == MERCHANT_INTEL_VERSION)
                .order_by(MerchantProfile.post_count_owned.desc()))]


def merchant_opportunities(s: Session) -> list[dict]:
    return [{"merchant": o.merchant_key, "kind": o.kind, "description": o.description,
             "confidence": o.confidence}
            for o in s.scalars(select(MerchantOpportunity)
                .where(MerchantOpportunity.intel_version == MERCHANT_INTEL_VERSION)
                .order_by(MerchantOpportunity.confidence.desc()))]


def owned_merchant_coverage(s: Session) -> dict:
    """Fraction of OWNED normalized posts that resolved to a known merchant."""
    total = s.scalar(select(func.count()).select_from(NormalizedPost)
                      .where(NormalizedPost.source_type == SourceType.OWNED)) or 0
    resolved = s.scalar(select(func.count()).select_from(NormalizedPost)
                         .where(NormalizedPost.source_type == SourceType.OWNED,
                                NormalizedPost.primary_merchant_key.isnot(None))) or 0
    return {"resolved": resolved, "total": total, "pct": (resolved / total) if total else 0.0}


def merchant_mix(s: Session, owned_coverage_pct: float | None = None) -> dict:
    """Us-vs-competitors merchant mix: each channel's share of its merchant-resolved
    posts per merchant (shares sum to ~1.0 per channel)."""
    from src.services.intelligence.competitor import latest_profiles

    channels: list[dict] = []

    owned_counts = dict(s.execute(
        select(NormalizedPost.primary_merchant_key, func.count(NormalizedPost.id))
        .where(NormalizedPost.source_type == SourceType.OWNED,
               NormalizedPost.primary_merchant_key.isnot(None))
        .group_by(NormalizedPost.primary_merchant_key)
    ).all())
    owned_resolved = sum(owned_counts.values())
    if owned_resolved:
        channels.append({
            "name": "You", "is_owned": True, "resolved_posts": owned_resolved,
            "coverage_pct": owned_coverage_pct,
            "shares": {k: v / owned_resolved for k, v in owned_counts.items()},
        })

    for p in latest_profiles(s):
        mix = p.merchant_mix or {}
        resolved = sum(mix.values())
        if not resolved:
            continue
        channels.append({
            "name": p.username, "is_owned": False, "resolved_posts": resolved,
            "coverage_pct": p.merchant_coverage,
            "shares": {k: v / resolved for k, v in mix.items()},
        })

    owned_shares = next((c["shares"] for c in channels if c["is_owned"]), {})
    all_merchants = {m for c in channels for m in c["shares"]}
    # Only keep merchants with >=1% share in at least one channel (filter out one-off links)
    significant = {m for m in all_merchants
                   if any(c["shares"].get(m, 0) >= 0.01 for c in channels)}
    merchants_sorted = sorted(significant, key=lambda m: -owned_shares.get(m, 0.0))

    return {"merchants": merchants_sorted, "channels": channels}


def competitor_profiles(s: Session) -> list[dict]:
    from src.db.models import Competitor
    from src.services.intelligence.competitor import latest_profiles

    profiles = sorted(latest_profiles(s), key=lambda p: -(p.post_count or 0))
    # join in title/category from the raw Competitor row (not stored on the profile
    # snapshot itself) -- same lookup pattern as service.competitor_dashboard().
    raw_by_id = {c.id: c for c in s.scalars(select(Competitor)).all()}
    return [{
        "competitor": p.username,
        "title": raw_by_id[p.competitor_id].title if p.competitor_id in raw_by_id else None,
        "category": (raw_by_id[p.competitor_id].category if p.competitor_id in raw_by_id else None) or "unclassified",
        "posts": p.post_count, "span_days": p.span_days,
        "posts_per_day": p.posts_per_day,
        "avg_text_len": p.avg_text_len, "emoji_rate": p.emoji_rate,
        "hashtag_rate": p.hashtag_rate, "cta_rate": p.cta_rate,
        "coupon_rate": p.coupon_rate, "multi_deal_rate": p.multi_deal_rate,
        "avg_links": p.avg_links, "media_rate": p.media_rate,
        "avg_views": p.avg_views, "views_sample_size": p.views_sample_size,
        "top_hour_ist": p.top_posting_hour_ist,
        "weekday_distribution": p.weekday_distribution,
        "hour_distribution_ist": p.hour_distribution_ist,
        "deal_mix": p.deal_mix, "merchant_mix": p.merchant_mix,
        "merchant_coverage": p.merchant_coverage,
        "similarity_to_us": p.similarity_to_owned, "confidence": p.confidence,
    } for p in profiles]


def available_deals(s: Session, limit: int = 15) -> list[dict]:
    """Active/valid deals from the live feed (EnrichedDeal) — the pool the planner
    themes slots around.

    Diversified by merchant instead of a raw discount-desc top-N: we pull a wide
    candidate set (still discount-ordered) then round-robin across merchants, so one
    merchant's deep discounts can't crowd every other merchant/category out of the
    menu the planner sees. That top-15-by-discount pool was a root cause of the
    'always one merchant/category' symptom. Degrades correctly to a single merchant
    when the feed genuinely only carries one that day."""
    from collections import OrderedDict

    from src.db.models_generation import DealValidity, EnrichedDeal
    candidates = s.scalars(
        select(EnrichedDeal)
        .where(EnrichedDeal.deal_validity != DealValidity.INVALID)
        .order_by(EnrichedDeal.discount_percent.is_(None),
                  EnrichedDeal.discount_percent.desc())
        .limit(300)
    ).all()

    by_merchant: "OrderedDict[str, list]" = OrderedDict()   # discount-ordered per merchant
    for d in candidates:
        by_merchant.setdefault(d.merchant_key or "?", []).append(d)

    picked = []
    while len(picked) < limit and any(by_merchant.values()):
        for lst in by_merchant.values():
            if lst:
                picked.append(lst.pop(0))
                if len(picked) >= limit:
                    break

    return [{"deal_id": d.deal_id, "title": d.title, "merchant_key": d.merchant_key,
             "category": d.category, "current_price": d.current_price,
             "discount_percent": d.discount_percent, "url": d.clean_url or d.url} for d in picked]


def full_briefing_context(s: Session, weekly: bool = False) -> dict:
    """Everything the briefing generator needs, as one grounded bundle."""
    out = {
        "channel": channel_overview(s),
        "what_changed_and_why": reasoning_insights(s),
        "growth_recommendations": growth_recommendations(s),
        "post_type_performance": post_type_performance(s),
        "merchant_opportunities": merchant_opportunities(s),
        "channel_style": channel_style(s),
        "competitor_benchmark": competitor_benchmark(s),
    }
    if weekly:
        from datetime import date as _date

        from src.services.analytics.daily_report import _owned_channel

        traj = posting_trajectory(s, days=7)
        week_start = _date.fromisoformat(traj["days"][0]["date"]) if traj["days"] else None
        end_day = _date.fromisoformat(traj["days"][-1]["date"]) if traj["days"] else None
        out["prev_week_digest"] = prev_week_digest(s, week_start) if week_start else None
        ch = _owned_channel(s)
        out["follower_deltas"] = (
            follower_deltas_by_day(s, ch.id if ch else None, week_start, end_day)
            if week_start and end_day else {}
        )
        # 30-day window: a week is too few days to split for a style→follower signal.
        out["style_follower_correlation"] = style_follower_correlation(s, days=30, end_day=end_day)
        out["retro"] = latest_retro(s)
    return out


def to_json(data: dict | list) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


_REPORT_NUMERIC = (
    "posts_count", "deals_posted", "merchants_featured", "views_total",
    "views_avg", "views_median", "views_max", "views_min",
    "reactions_total", "forwards_total", "engagement_rate", "subs_net",
)


def _report_to_dict(r) -> dict:
    return {
        "report_date": r.report_date.isoformat() if r.report_date else None,
        "source_type": r.source_type,
        "posts_count": r.posts_count, "deals_posted": r.deals_posted,
        "merchants_featured": r.merchants_featured,
        "views_total": r.views_total, "views_avg": r.views_avg,
        "views_median": r.views_median, "views_max": r.views_max, "views_min": r.views_min,
        "reactions_total": r.reactions_total, "forwards_total": r.forwards_total,
        "engagement_rate": r.engagement_rate,
        "subs_start": r.subs_start, "subs_end": r.subs_end, "subs_net": r.subs_net,
        "type_mix": r.type_mix, "category_mix": r.category_mix, "posting_hours": r.posting_hours,
        "best_category": r.best_category, "worst_category": r.worst_category,
        "data_completeness": r.data_completeness, "id": r.id,
    }


def daily_reports(s: Session, days: int = 8, source_type: str | None = None) -> list[dict]:
    from src.db.models_report import DailyChannelReport, ReportSourceType
    src_t = source_type or ReportSourceType.OWNED
    rows = list(s.scalars(
        select(DailyChannelReport)
        .where(DailyChannelReport.source_type == src_t)
        .order_by(DailyChannelReport.report_date.desc())
        .limit(days)
    ))
    return [_report_to_dict(r) for r in rows]


def report_baseline(s: Session, days: int = 30) -> dict:
    rows = daily_reports(s, days=days)
    if not rows:
        return {}
    out = {}
    for k in _REPORT_NUMERIC:
        vals = [r[k] for r in rows if r.get(k) is not None]
        out[k] = round(sum(vals) / len(vals), 2) if vals else 0
    return out


def planning_context(s: Session) -> dict:
    from src.db.models_report import ReportSourceType
    return {
        "channel": channel_overview(s),
        "reports": daily_reports(s, days=8, source_type=ReportSourceType.OWNED),
        "baseline": report_baseline(s, days=30),
        "competitor_reports": daily_reports(s, days=8, source_type=ReportSourceType.COMPETITOR),
        "channel_style": channel_style(s),
        "post_type_performance": post_type_performance(s),
    }


def daily_report_or_live(s: Session, day) -> dict:
    """Owned day-facts for ``day``: always computed live (avoids stale cached
    reports). Always returns a dict; ``source`` is 'live' or 'none'."""
    from src.services.analytics.daily_report import build_owned_report
    live = build_owned_report(s, day)
    d = _report_to_dict(live)
    d["source"] = "live" if live.posts_count else "none"
    return d


def scheduled_count_today(s: Session, day=None) -> int:
    """Count of `ScheduledPost` rows due on ``day`` (IST calendar date, defaulting
    to the latest owned-post day) — i.e. what's actually queued to post that day,
    as opposed to `posting_trajectory`'s purely historical cadence target.

    `CANCELLED` rows are excluded (they were pulled from the plan); every other
    status (queued/retry/sending/published/failed/blocked) still counts as "was
    scheduled for that day" for reconciliation purposes against the recommended
    cadence.
    """
    from src.db.models_automation import ScheduledPost, ScheduleStatus
    from src.services.analytics.day import latest_owned_date
    from src.services.analytics.periods import ist_day_bounds_utc

    if day is None:
        day = latest_owned_date(s)
    if day is None:
        return 0
    start, end = ist_day_bounds_utc(day)
    return s.scalar(
        select(func.count()).select_from(ScheduledPost)
        .where(ScheduledPost.scheduled_at >= start, ScheduledPost.scheduled_at < end,
               ScheduledPost.status != ScheduleStatus.CANCELLED)
    ) or 0


def posting_trajectory(s: Session, days: int = 14, end_day=None) -> dict:
    """Per-IST-day owned posting counts over the last ``days`` (ending at ``end_day``
    or the latest owned day). Returns the day series plus ``recent_cadence`` (median
    posts/day over ACTIVE days — the honest 'what you actually post') and the stale
    ``lifetime_baseline`` from the growth blueprint, for contrast."""
    from datetime import timedelta
    from statistics import median

    from src.db.models import Post
    from src.services.analytics.day import latest_owned_date
    from src.services.analytics.daily_report import _owned_channel
    from src.services.analytics.periods import ist_day_bounds_utc, to_ist

    if end_day is None:
        end_day = latest_owned_date(s)
    if end_day is None:
        return {"days": [], "recent_cadence": 0, "lifetime_baseline": None}

    first_day = end_day - timedelta(days=days - 1)
    start_utc, _ = ist_day_bounds_utc(first_day)
    _, end_utc = ist_day_bounds_utc(end_day)
    ch = _owned_channel(s)
    q = select(Post.posted_at, Post.views).where(
        Post.posted_at >= start_utc, Post.posted_at < end_utc)
    if ch is not None:
        q = q.where(Post.channel_id == ch.id)

    from collections import defaultdict
    counts: dict = defaultdict(int)
    view_sums: dict = defaultdict(float)
    for posted_at, views in s.execute(q).all():
        if posted_at is None:
            continue
        d = to_ist(posted_at).date()
        counts[d] += 1
        view_sums[d] += (views or 0)

    series = []
    for i in range(days):
        d = first_day + timedelta(days=i)
        n = counts.get(d, 0)
        series.append({"date": d.isoformat(), "posts": n,
                       # raw per-day total so callers can sum TRUE views instead of
                       # reconstructing from posts x rounded-avg (which drifts).
                       "views": round(view_sums[d]),
                       "views_avg": round(view_sums[d] / n, 1) if n else 0.0})

    active = [r["posts"] for r in series if r["posts"] > 0]
    cadence = int(round(median(active))) if active else 0
    bp = (growth_blueprint(s).get("blueprint") or {})
    lifetime = bp.get("posting_frequency_baseline")
    return {"days": series, "recent_cadence": cadence,
            "lifetime_baseline": round(lifetime, 1) if lifetime else None}


def clamp_recommended_posts(
    candidate, recent_median: int, recent_max_30d: int | None = None
) -> tuple[int, bool]:
    """Safety-clamp the AI's own `recommended_posts` headline before it reaches a user.

    `candidate=None`/unparseable is an AI-unavailable fallback, not a clamp event —
    returns `recent_median` with `False` so the caller doesn't set `plan_clamped`.
    Otherwise: floor of 1 while there's active recent cadence (never silently accept
    0 unless `recent_median` itself is 0 — a genuine pause); ceiling of
    `3 * recent_max_30d`, or `max(3 * recent_median, 5)` when `recent_max_30d` is
    unavailable/zero.
    """
    if candidate is None:
        return int(recent_median or 0), False
    try:
        value = int(round(float(candidate)))
    except (TypeError, ValueError):
        return int(recent_median or 0), False

    floor = 1 if recent_median and recent_median > 0 else 0
    ceiling = 3 * recent_max_30d if recent_max_30d else max(3 * (recent_median or 0), 5)

    clamped = min(max(value, floor), ceiling)
    return clamped, clamped != value


def prev_week_digest(s: Session, week_start) -> str | None:
    """Previous week's AI narrative: the WEEKLY `CampaignPlan` whose `end_date` falls
    immediately before `week_start`, so this week's briefing can build on it instead
    of restating from scratch. `None` when absent or not AI-generated."""
    from datetime import timedelta

    from src.db.models_campaign import CAMPAIGN_VERSION, CampaignPlan, PlanType

    prev_end = week_start - timedelta(days=1)
    wk = s.scalar(
        select(CampaignPlan)
        .where(CampaignPlan.campaign_version == CAMPAIGN_VERSION,
               CampaignPlan.plan_type == PlanType.WEEKLY,
               CampaignPlan.end_date == prev_end)
        .order_by(CampaignPlan.generated_at.desc())
    )
    if wk and wk.is_ai_generated and wk.ai_digest:
        return wk.ai_digest
    return None


def latest_retro(s: Session) -> dict | None:
    """Most recent ``WeeklyRetro``'s metrics + narrative (Phase 2.4), modeled on
    ``prev_week_digest`` above — lets the weekly briefing/plan build on last
    week's rule-based ``adjustments`` instead of restating from scratch. `None`
    when no retro has run yet."""
    from src.db.models_prediction import WeeklyRetro

    row = s.scalar(select(WeeklyRetro).order_by(WeeklyRetro.week_start.desc()))
    if row is None:
        return None
    return {"week_start": row.week_start.isoformat(), "metrics": row.metrics, "narrative": row.narrative}


def follower_deltas_by_day(s: Session, channel_id: int | None, start_day, end_day) -> dict[str, dict]:
    """Per-IST-day joined/left/net follower counts for `channel_id` over
    [start_day, end_day], keyed by ISO date — drops in alongside `posting_trajectory`'s
    day series for the weekly view. Days with no `DailySubscriberStat` row are simply
    absent from the result (the caller decides the gap-fill default)."""
    from src.db.models_growth_snapshot import DailySubscriberStat

    if channel_id is None:
        return {}
    rows = s.scalars(
        select(DailySubscriberStat)
        .where(DailySubscriberStat.channel_id == channel_id,
               DailySubscriberStat.stat_date >= start_day,
               DailySubscriberStat.stat_date <= end_day)
    ).all()
    return {r.stat_date.isoformat(): {"joined": r.subs_joined or 0,
                                       "left": r.subs_left or 0,
                                       "net": r.subs_net or 0}
            for r in rows}


# Min paired (posts + follower delta) days before the style→follower correlation is
# offered as a signal at all. Deliberately low — this is a small, day-level, honest
# correlation; it is never treated as causal (see the prompt guardrails).
_MIN_CORRELATION_DAYS = 4


def daily_style_by_day(s: Session, days: int = 14, end_day=None) -> dict:
    """Per-IST-day style features of OWNED posts over the last ``days`` (ending at
    ``end_day`` or the latest owned day): posts, emoji_density (avg emojis/post),
    avg_caption_len, loot_share, coupon_rate, cta_rate, media_rate, top_hour_ist.

    Same window/day-bucketing as ``posting_trajectory``, and the SAME per-post feature
    source the Channel Learning Engine uses (OWNED ``NormalizedPost`` joined to ``Post``)
    — this is the day-resolution view of the channel's own style, so the planner can line
    it up against ``follower_deltas_by_day``. Read-only; no LLM, no persistence."""
    from collections import Counter, defaultdict
    from datetime import timedelta
    from statistics import fmean

    from src.db.models import Post
    from src.db.models_normalization import NormalizedPost, SourceType
    from src.services.analytics.day import latest_owned_date
    from src.services.analytics.daily_report import _owned_channel
    from src.services.analytics.periods import ist_day_bounds_utc, to_ist

    if end_day is None:
        end_day = latest_owned_date(s)
    if end_day is None:
        return {"days": []}

    first_day = end_day - timedelta(days=days - 1)
    start_utc, _ = ist_day_bounds_utc(first_day)
    _, end_utc = ist_day_bounds_utc(end_day)
    ch = _owned_channel(s)
    q = (
        select(Post.posted_at, func.length(Post.text), Post.has_media,
               NormalizedPost.emojis, NormalizedPost.has_coupon,
               NormalizedPost.is_multi_deal, NormalizedPost.cta_texts)
        .select_from(Post)
        .join(NormalizedPost, (NormalizedPost.source_id == Post.id)
              & (NormalizedPost.source_type == SourceType.OWNED))
        .where(Post.posted_at >= start_utc, Post.posted_at < end_utc)
    )
    if ch is not None:
        q = q.where(Post.channel_id == ch.id)

    buckets: dict = defaultdict(list)
    for posted_at, tlen, media, emojis, coupon, multi, cta in s.execute(q).all():
        if posted_at is None:
            continue
        ist = to_ist(posted_at)
        buckets[ist.date()].append({
            "hour": ist.hour, "caption_len": tlen or 0, "media": bool(media),
            "emojis": len(emojis or []), "coupon": bool(coupon),
            "multi": bool(multi), "cta": bool(cta),
        })

    out = []
    for i in range(days):
        d = first_day + timedelta(days=i)
        rows = buckets.get(d, [])
        n = len(rows)
        if not n:
            out.append({"date": d.isoformat(), "posts": 0})
            continue
        top_hour = Counter(r["hour"] for r in rows).most_common(1)[0][0]
        out.append({
            "date": d.isoformat(), "posts": n,
            "emoji_density": round(fmean(r["emojis"] for r in rows), 2),
            "avg_caption_len": round(fmean(r["caption_len"] for r in rows), 1),
            "loot_share": round(sum(r["multi"] for r in rows) / n, 2),
            "coupon_rate": round(sum(r["coupon"] for r in rows) / n, 2),
            "cta_rate": round(sum(r["cta"] for r in rows) / n, 2),
            "media_rate": round(sum(r["media"] for r in rows) / n, 2),
            "top_hour_ist": top_hour,
        })
    return {"days": out}


def _style_follower_split(paired: list[dict], feature: str) -> dict | None:
    """Split ``paired`` days at the median of ``feature`` and compare each half's mean
    net follower change. Returns None unless both halves have >= 2 days (small-sample
    honesty — a one-day 'group' is noise, not a signal)."""
    from statistics import fmean, median

    vals = [r[feature] for r in paired if r.get(feature) is not None]
    if len(vals) < 4:
        return None
    med = median(vals)
    high = [r["followers_net"] for r in paired if (r.get(feature) or 0) > med]
    low = [r["followers_net"] for r in paired if (r.get(feature) or 0) <= med]
    if len(high) < 2 or len(low) < 2:
        return None
    return {"feature": feature, "split_at": round(med, 2),
            "high_days_avg_net": round(fmean(high), 1), "n_high_days": len(high),
            "low_days_avg_net": round(fmean(low), 1), "n_low_days": len(low)}


def style_follower_correlation(s: Session, days: int = 14, end_day=None) -> dict:
    """Line up each day's OWNED post-style features (``daily_style_by_day``) with that
    day's net follower change (``follower_deltas_by_day``), plus a few median-split
    comparisons (loot-heavy vs not, media-heavy vs not, etc.).

    This is CORRELATIONAL and day-level by construction: Telegram attributes joins to a
    day, never to a single post, so this shows 'days styled like X averaged N net joins',
    never 'this post caused a join'. Sample sizes are returned so the reader can weigh it;
    ``available`` is False until there are >= ``_MIN_CORRELATION_DAYS`` paired days."""
    from datetime import date as _date

    from src.services.analytics.daily_report import _owned_channel

    style_days = daily_style_by_day(s, days=days, end_day=end_day)["days"]
    ch = _owned_channel(s)
    if not style_days or ch is None:
        return {"available": False, "reason": "no owned posting history / channel"}

    first = _date.fromisoformat(style_days[0]["date"])
    last = _date.fromisoformat(style_days[-1]["date"])
    deltas = follower_deltas_by_day(s, ch.id, first, last)

    rows = []
    for d in style_days:
        fd = deltas.get(d["date"]) or {}
        rows.append({**d,
                     "followers_joined": fd.get("joined"),
                     "followers_left": fd.get("left"),
                     "followers_net": fd.get("net")})

    paired = [r for r in rows if r.get("posts") and r.get("followers_net") is not None]
    comparisons = [c for c in (_style_follower_split(paired, f)
                   for f in ("loot_share", "media_rate", "coupon_rate",
                             "cta_rate", "emoji_density"))
                   if c is not None]
    return {"available": len(paired) >= _MIN_CORRELATION_DAYS, "n_days": len(paired),
            "note": "day-level correlation, not causal; joins are per-day, not per-post",
            "days": rows, "comparisons": comparisons}


def competitor_benchmark(s: Session) -> dict:
    """Compact us-vs-competitors comparison for the planner: aggregate competitor style
    (posts/day, avg views, cta/coupon/multi-deal/media rates), our own style, and a
    per-merchant share comparison — all derived from the already-collected competitor
    profiles + ``merchant_mix``. Summarized (not full profile dumps) to keep prompt cost
    sane, and shaped as flat dicts so cited numbers stay fact-checkable."""
    from statistics import fmean

    profs = competitor_profiles(s)
    if not profs:
        return {"available": False, "reason": "no competitor profiles yet"}

    def _avg(key: str):
        vals = [p[key] for p in profs if p.get(key) is not None]
        return round(fmean(vals), 3) if vals else None

    ours = channel_style(s)
    mm = merchant_mix(s)
    owned = next((c for c in mm.get("channels", []) if c.get("is_owned")), None)
    comp_channels = [c for c in mm.get("channels", []) if not c.get("is_owned")]
    merchant_rows = []
    for m in (mm.get("merchants") or [])[:8]:
        comp_shares = [c["shares"].get(m, 0.0) for c in comp_channels]
        merchant_rows.append({
            "merchant": m,
            "our_share": round(owned["shares"].get(m, 0.0), 3) if owned else None,
            "competitor_avg_share": round(fmean(comp_shares), 3) if comp_shares else None,
        })

    return {
        "available": True,
        "n_competitors": len(profs),
        "competitors_avg": {
            "posts_per_day": _avg("posts_per_day"), "avg_views": _avg("avg_views"),
            "cta_rate": _avg("cta_rate"), "coupon_rate": _avg("coupon_rate"),
            "multi_deal_rate": _avg("multi_deal_rate"), "media_rate": _avg("media_rate"),
        },
        "ours": {
            "posts_per_day": ours.get("posts_per_day"), "cta_rate": ours.get("cta_rate"),
            "coupon_rate": ours.get("coupon_rate"), "multi_deal_rate": ours.get("multi_deal_rate"),
            "media_rate": ours.get("media_rate"),
        } if ours.get("available") else {"available": False},
        "merchant_share_vs_competitors": merchant_rows,
    }
