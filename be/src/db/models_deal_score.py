"""Phase 3.1 storage -- DealScoringEngine history
(``src/services/intelligence/deal_scoring.py``).

One row per deal per scoring run (never overwritten in place), so the score's
trend over time is queryable -- distinct from ``EnrichedDeal.rank_score`` /
``score_breakdown``, which ``DealRanker`` (``generation/ranking.py``) still
writes at draft-generation time and which this table never touches.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class DealScore(Base):
    __tablename__ = "deal_scores"
    __table_args__ = (Index("ix_deal_scores_scored_score", "scored_at", "score"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("enriched_deals.id"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)      # 0..100
    components: Mapped[dict] = mapped_column(JSON, nullable=False)   # 6 normalized [0,1] components
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
