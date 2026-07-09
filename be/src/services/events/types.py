"""Event type vocabulary and the Event dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class EventType:
    """Canonical collection events (spec 08). Extend as new collectors arrive."""

    POST_COLLECTED = "PostCollected"
    POST_UPDATED = "PostUpdated"
    POST_DELETED = "PostDeleted"
    POST_METRICS_UPDATED = "PostMetricsUpdated"
    CHANNEL_UPDATED = "ChannelUpdated"
    CHANNEL_STATS_UPDATED = "ChannelStatsUpdated"
    COMPETITOR_UPDATED = "CompetitorUpdated"
    COMPETITOR_POST_COLLECTED = "CompetitorPostCollected"
    MERCHANT_UPDATED = "MerchantUpdated"
    PRODUCT_UPDATED = "ProductUpdated"
    PRICE_CHANGED = "PriceChanged"
    AFFILIATE_LINK_UPDATED = "AffiliateLinkUpdated"
    DISCOVERY_COMPLETED = "DiscoveryCompleted"
    # --- Phase 2: normalization events ---
    POST_NORMALIZED = "PostNormalized"
    DEAL_EXTRACTED = "DealExtracted"
    MERCHANT_DETECTED = "MerchantDetected"
    PRICE_EXTRACTED = "PriceExtracted"
    # --- Phase 3: classification events ---
    POST_CLASSIFIED = "PostClassified"
    CLUSTERS_UPDATED = "ClustersUpdated"
    # --- Phase 4: merchant intelligence events ---
    MERCHANT_PROFILE_UPDATED = "MerchantProfileUpdated"
    MERCHANT_OPPORTUNITY_DETECTED = "MerchantOpportunityDetected"
    # --- Phase 5: competitor intelligence events ---
    COMPETITOR_STRATEGY_UPDATED = "CompetitorStrategyUpdated"
    # --- Phase 6: channel learning events ---
    LEARNING_RECORDED = "LearningRecorded"
    KNOWLEDGE_UPDATED = "KnowledgeUpdated"
    # --- Phase 7: growth engine events ---
    GROWTH_STRATEGY_GENERATED = "GrowthStrategyGenerated"
    GROWTH_RECOMMENDATION_ISSUED = "GrowthRecommendationIssued"
    POSTING_PLAN_CREATED = "PostingPlanCreated"
    # --- Phase 8: reasoning events ---
    PERFORMANCE_SHIFT_DETECTED = "PerformanceShiftDetected"
    INSIGHT_GENERATED = "InsightGenerated"
    # --- Phase 9: enrichment + post generation events ---
    DEAL_ENRICHED = "DealEnriched"
    POST_GENERATED = "PostGenerated"
    POST_PUBLISHED = "PostPublished"
    # --- Phase 10: campaign & planning events ---
    PLAN_GENERATED = "PlanGenerated"
    CAMPAIGN_GENERATED = "CampaignGenerated"
    # --- Phase 11: automation / scheduled posting events ---
    POST_SCHEDULED = "PostScheduled"
    POST_SEND_ATTEMPTED = "PostSendAttempted"
    POST_SEND_FAILED = "PostSendFailed"
    POST_SEND_BLOCKED = "PostSendBlocked"


@dataclass(slots=True)
class Event:
    event_type: str
    entity_type: str
    entity_id: str
    data: dict[str, Any] = field(default_factory=dict)
    job_id: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
