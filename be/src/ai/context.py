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


def channel_overview(s: Session, channel_id: int | None = None) -> dict:
    q = select(Channel)
    q = q.where(Channel.id == channel_id) if channel_id is not None \
        else q.order_by(Channel.participants_count.desc())
    ch = s.scalars(q).first()
    if not ch:
        return {"available": False}
    return {"available": True, "title": ch.title, "username": ch.username,
            "subscribers": ch.participants_count}


def _owned_window_desc(s: Session, channel_id: int | None = None) -> str:
    from src.services.analytics.periods import owned_window
    w = owned_window(s, channel_id=channel_id)
    return f"owned, last {w['months']} mo"


def reasoning_insights(s: Session, channel_id: int | None = None) -> list[dict]:
    q = select(ReasonedInsight).where(ReasonedInsight.reasoning_version == REASONING_VERSION)
    if channel_id is not None:
        q = q.where(ReasonedInsight.channel_id == channel_id)
    return [{"metric": i.metric, "direction": i.direction,
             "change": i.change_value, "unit": i.change_unit,
             "observation": i.observation, "why": i.reasoning,
             "period": i.period_label, "evidence": i.evidence,
             "confidence": i.confidence}
            for i in s.scalars(q.order_by(ReasonedInsight.confidence.desc()))]


def growth_recommendations(s: Session, limit: int = 8, channel_id: int | None = None) -> list[dict]:
    q = select(GrowthRecommendation).where(GrowthRecommendation.growth_version == GROWTH_VERSION)
    if channel_id is not None:
        q = q.where(GrowthRecommendation.channel_id == channel_id)
    return [{"priority": r.priority, "category": r.category,
             "recommendation": r.recommendation, "reasoning": r.reasoning,
             "evidence": r.evidence, "confidence": r.confidence,
             "expected_outcome": r.expected_outcome}
            for r in s.scalars(q.order_by(GrowthRecommendation.priority).limit(limit))]


def growth_blueprint(s: Session, channel_id: int | None = None) -> dict:
    q = select(GrowthStrategy).where(GrowthStrategy.growth_version == GROWTH_VERSION)
    if channel_id is not None:
        q = q.where(GrowthStrategy.channel_id == channel_id)
    strat = s.scalar(q)
    if not strat:
        return {"available": False}
    return {"available": True, "mode": strat.mode, "channel_type": strat.channel_type,
            "blueprint": strat.blueprint, "confidence": strat.confidence}


def post_type_performance(s: Session, channel_id: int | None = None) -> list[dict]:
    q = select(PostTypePerformance).where(PostTypePerformance.learning_version == LEARNING_VERSION)
    if channel_id is not None:
        q = q.where(PostTypePerformance.channel_id == channel_id)
    return [{"post_type": p.post_type, "posts": p.post_count, "share": p.share,
             "avg_views_per_day": p.avg_views_per_day, "rank": p.rank_by_views_per_day}
            for p in s.scalars(q.order_by(PostTypePerformance.rank_by_views_per_day))]


def learnings(s: Session, channel_id: int | None = None) -> list[dict]:
    window = _owned_window_desc(s, channel_id=channel_id)
    q = select(LearningRecord).where(LearningRecord.learning_version == LEARNING_VERSION)
    if channel_id is not None:
        q = q.where(LearningRecord.channel_id == channel_id)
    out = []
    for r in s.scalars(q.order_by(LearningRecord.confidence.desc())):
        how = None
        if r.metric_value is not None and r.comparison_value:
            lift = (r.metric_value / r.comparison_value - 1) * 100
            how = (f"{r.metric_value:.1f} vs {r.comparison_value:.1f} {r.metric_name or 'views/day'} "
                   f"= {lift:+.0f}% · n={r.sample_size:,} · {window} · age-normalized")
        out.append({"category": r.category, "statement": r.statement,
                    "confidence": r.confidence, "sample_size": r.sample_size,
                    "how_calculated": how, "period": window})
    return out


def channel_style(s: Session, channel_id: int | None = None) -> dict:
    q = select(ChannelStyleProfile).where(ChannelStyleProfile.learning_version == LEARNING_VERSION)
    if channel_id is not None:
        q = q.where(ChannelStyleProfile.channel_id == channel_id)
    st = s.scalar(q)
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
    return [{"competitor": p.username, "posts": p.post_count,
             "similarity_to_us": p.similarity_to_owned,
             "top_hour_ist": p.top_posting_hour_ist}
            for p in s.scalars(select(CompetitorProfile)
                .where(CompetitorProfile.intel_version == COMPETITOR_INTEL_VERSION)
                .order_by(CompetitorProfile.post_count.desc()))]


def full_briefing_context(s: Session, channel_id: int | None = None) -> dict:
    """Everything the briefing generator needs, as one grounded bundle.

    Owned-channel context is scoped to channel_id when given; merchant and competitor
    context is shared market data (competitor scoping is per-org, handled elsewhere)."""
    return {
        "channel": channel_overview(s, channel_id=channel_id),
        "what_changed_and_why": reasoning_insights(s, channel_id=channel_id),
        "growth_recommendations": growth_recommendations(s, channel_id=channel_id),
        "post_type_performance": post_type_performance(s, channel_id=channel_id),
        "competitor_signals": competitor_signals(s),
        "merchant_opportunities": merchant_opportunities(s),
        "channel_style": channel_style(s, channel_id=channel_id),
    }


def to_json(data: dict | list) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
