"""Phase 9 storage — Deal Enrichment + Post Generation.

EnrichedDeal mirrors the output contract in source_truth/06_data_enrichment_engine.md
(the "truth layer"): raw scraped deals become validated, structured objects with
explicit UNKNOWN fields and a price-confidence score. GeneratedPost is the ranked,
selected, formatted output the operator reviews before publishing.

Honesty: affiliate links are NULL until GrabOn's own shortener/affiliate system is
integrated (deferred); publishing is gated on channel admin rights + explicit
confirmation — never auto-sent.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin

UNKNOWN = "unknown"


class DealValidity:
    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class PostStatus:
    DRAFT = "draft"          # generated, awaiting review
    APPROVED = "approved"    # operator approved, not yet sent
    PUBLISHED = "published"
    BLOCKED = "blocked"      # cannot publish (no rights / integration missing)


class EnrichedDeal(Base, TimestampMixin):
    __tablename__ = "enriched_deals"
    __table_args__ = (
        UniqueConstraint("deal_id", name="uq_enriched_deal_id"),
        Index("ix_enriched_merchant", "merchant_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[str] = mapped_column(String(64), nullable=False)   # content-hash id
    source: Mapped[str] = mapped_column(String(64), default="manual")  # grabcash_api | manual | ...

    title: Mapped[str | None] = mapped_column(String(1024))
    url: Mapped[str | None] = mapped_column(String(1024))
    clean_url: Mapped[str | None] = mapped_column(String(1024))
    image: Mapped[str | None] = mapped_column(String(1024))

    merchant_key: Mapped[str | None] = mapped_column(String(64))       # None = UNKNOWN
    merchant_type: Mapped[str] = mapped_column(String(32), default=UNKNOWN)
    category: Mapped[str] = mapped_column(String(64), default=UNKNOWN)  # not extracted yet

    original_price: Mapped[float | None] = mapped_column(Float)         # MRP
    current_price: Mapped[float | None] = mapped_column(Float)
    discount_percent: Mapped[float | None] = mapped_column(Float)

    is_loot_deal: Mapped[bool | None] = mapped_column(Boolean)          # None = undetermined
    deal_validity: Mapped[str] = mapped_column(String(16), default=DealValidity.UNKNOWN)
    price_confidence_score: Mapped[float] = mapped_column(Float, default=0.0)

    affiliate_link: Mapped[str | None] = mapped_column(String(1024))    # deferred -> NULL
    tags: Mapped[list | None] = mapped_column(JSON)
    enrichment_source: Mapped[list | None] = mapped_column(JSON)
    raw_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("raw_snapshots.id"))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ranking output (set by the ranker)
    rank_score: Mapped[float | None] = mapped_column(Float)
    score_breakdown: Mapped[dict | None] = mapped_column(JSON)


class GeneratedPost(Base, TimestampMixin):
    __tablename__ = "generated_posts"
    __table_args__ = (Index("ix_genpost_status", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    post_type: Mapped[str] = mapped_column(String(64))                 # single | collection
    selection_bucket: Mapped[str | None] = mapped_column(String(32))  # loot/budget/high-value/...
    deal_ids: Mapped[list] = mapped_column(JSON)                       # enriched deal_id(s)
    rendered_text: Mapped[str] = mapped_column(Text, nullable=False)
    format_meta: Mapped[dict | None] = mapped_column(JSON)
    rank_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default=PostStatus.DRAFT)
    publish_note: Mapped[str | None] = mapped_column(Text)
    channel_ref: Mapped[str | None] = mapped_column(String(128))
    # why this draft follows the strategy: post-type/perf, target IST window, emoji policy,
    # expected views — each with its period + sample so it never reads as vague.
    strategy_rationale: Mapped[dict | None] = mapped_column(JSON)
