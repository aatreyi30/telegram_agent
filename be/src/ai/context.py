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
             "confidence": p.confidence}
            for p in s.scalars(select(MerchantProfile)
                .where(MerchantProfile.intel_version == MERCHANT_INTEL_VERSION)
                .order_by(MerchantProfile.post_count_owned.desc()))]


def merchant_opportunities(s: Session) -> list[dict]:
    return [{"merchant": o.merchant_key, "kind": o.kind, "description": o.description,
             "confidence": o.confidence}
            for o in s.scalars(select(MerchantOpportunity)
                .where(MerchantOpportunity.intel_version == MERCHANT_INTEL_VERSION)
                .order_by(MerchantOpportunity.confidence.desc()))]


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
