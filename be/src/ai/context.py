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
from src.db.models_competitor_intel import (
    COMPETITOR_INTEL_VERSION,
    CompetitorProfile,
    CompetitorSignal,
)
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
    channels: list[dict] = []

    owned_counts = {p.merchant_key: p.post_count_owned
                    for p in s.scalars(select(MerchantProfile)
                        .where(MerchantProfile.intel_version == MERCHANT_INTEL_VERSION))
                    if p.post_count_owned}
    owned_resolved = sum(owned_counts.values())
    if owned_resolved:
        channels.append({
            "name": "You", "is_owned": True, "resolved_posts": owned_resolved,
            "coverage_pct": owned_coverage_pct,
            "shares": {k: v / owned_resolved for k, v in owned_counts.items()},
        })

    for p in s.scalars(select(CompetitorProfile)
            .where(CompetitorProfile.intel_version == COMPETITOR_INTEL_VERSION)):
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
    merchants_sorted = sorted(all_merchants, key=lambda m: -owned_shares.get(m, 0.0))

    return {"merchants": merchants_sorted, "channels": channels}


def competitor_signals(s: Session) -> list[dict]:
    return [{"type": sig.signal_type, "competitor": sig.username, "kind": sig.kind,
             "description": sig.description, "confidence": sig.confidence}
            for sig in s.scalars(select(CompetitorSignal)
                .where(CompetitorSignal.intel_version == COMPETITOR_INTEL_VERSION)
                .order_by(CompetitorSignal.confidence.desc()))]


def competitor_profiles(s: Session) -> list[dict]:
    return [{
        "competitor": p.username, "posts": p.post_count, "span_days": p.span_days,
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
    } for p in s.scalars(select(CompetitorProfile)
        .where(CompetitorProfile.intel_version == COMPETITOR_INTEL_VERSION)
        .order_by(CompetitorProfile.post_count.desc()))]


def full_briefing_context(s: Session) -> dict:
    """Everything the briefing generator needs, as one grounded bundle."""
    return {
        "channel": channel_overview(s),
        "what_changed_and_why": reasoning_insights(s),
        "growth_recommendations": growth_recommendations(s),
        "post_type_performance": post_type_performance(s),
        "competitor_signals": competitor_signals(s),
        "merchant_opportunities": merchant_opportunities(s),
        "channel_style": channel_style(s),
    }


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
    """Owned day-facts for ``day``: the persisted DailyChannelReport if one exists,
    otherwise computed live from that day's posts (never persisted). Always returns
    a dict; ``source`` is 'report', 'live', or 'none' (no activity that day)."""
    from src.db.models_report import DailyChannelReport, ReportSourceType
    r = s.scalars(
        select(DailyChannelReport).where(
            DailyChannelReport.source_type == ReportSourceType.OWNED,
            DailyChannelReport.report_date == day,
        )
    ).first()
    if r is not None:
        d = _report_to_dict(r)
        d["source"] = "report"
        return d
    from src.services.analytics.daily_report import build_owned_report
    live = build_owned_report(s, day)
    d = _report_to_dict(live)
    d["source"] = "live" if live.posts_count else "none"
    return d


def posting_trajectory(s: Session, days: int = 14, end_day=None) -> dict:
    """Per-IST-day owned posting counts over the last ``days`` (ending at ``end_day``
    or the latest owned day). Returns the day series plus ``recent_cadence`` (median
    posts/day over ACTIVE days — the honest 'what you actually post') and the stale
    ``lifetime_baseline`` from the growth blueprint, for contrast."""
    from datetime import timedelta, timezone
    from statistics import median

    from src.db.models import Post
    from src.services.analytics.day import latest_owned_date
    from src.services.analytics.daily_report import _ist_bounds, _owned_channel
    from src.services.analytics.periods import IST

    if end_day is None:
        end_day = latest_owned_date(s)
    if end_day is None:
        return {"days": [], "recent_cadence": 0, "lifetime_baseline": None}

    first_day = end_day - timedelta(days=days - 1)
    start_utc, _ = _ist_bounds(first_day)
    _, end_utc = _ist_bounds(end_day)
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
        if posted_at.tzinfo is None:
            posted_at = posted_at.replace(tzinfo=timezone.utc)
        d = posted_at.astimezone(IST).date()
        counts[d] += 1
        view_sums[d] += (views or 0)

    series = []
    for i in range(days):
        d = first_day + timedelta(days=i)
        n = counts.get(d, 0)
        series.append({"date": d.isoformat(), "posts": n,
                       "views_avg": round(view_sums[d] / n, 1) if n else 0.0})

    active = [r["posts"] for r in series if r["posts"] > 0]
    cadence = int(round(median(active))) if active else 0
    bp = (growth_blueprint(s).get("blueprint") or {})
    lifetime = bp.get("posting_frequency_baseline")
    return {"days": series, "recent_cadence": cadence,
            "lifetime_baseline": round(lifetime, 1) if lifetime else None}
