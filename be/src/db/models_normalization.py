"""Phase 2 storage — structured entities produced by the Normalization Engine.

Design (README/09_data_normalization_engine.md):
  * Deterministic: same raw input -> identical structured output.
  * Preserve UNKNOWN: never guess prices/merchants/categories.
  * Reference the raw source: every normalized row points back to its post.
  * Versioned: ``normalization_version`` allows future reprocessing.

Deal-TYPE classification (loot/coupon/collection) is intentionally absent — it
must be learned from patterns (RULE 3), which is Phase 3, not hardcoded here.
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
from src.db.models_classification import PostClassification

# Bump whenever the parsers/normalizer logic changes — triggers reprocessing of
# posts normalized under an older version (README/09 versioning requirement).
NORMALIZATION_VERSION = 2


class SourceType:
    """Which raw table a normalized post came from."""

    OWNED = "owned"
    COMPETITOR = "competitor"


class NormalizedPost(Base, TimestampMixin):
    """Structured view of one raw post (owned or competitor).

    Polymorphic by (source_type, source_id) rather than a hard FK, so one table
    covers both owned Posts and CompetitorPosts. ``raw_content_sha256`` lets the
    normalizer detect when a re-normalization is needed after an edit.
    """

    __tablename__ = "normalized_posts"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_normalized_source"),
        Index("ix_normalized_merchant", "primary_merchant_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)

    normalization_version: Mapped[int] = mapped_column(Integer, default=NORMALIZATION_VERSION)
    normalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_content_sha256: Mapped[str | None] = mapped_column(String(64))

    # parsed components (facts, no interpretation)
    language: Mapped[str] = mapped_column(String(16), default="unknown")
    emojis: Mapped[list | None] = mapped_column(JSON)
    hashtags: Mapped[list | None] = mapped_column(JSON)
    mentions: Mapped[list | None] = mapped_column(JSON)
    cta_texts: Mapped[list | None] = mapped_column(JSON)

    num_links: Mapped[int] = mapped_column(Integer, default=0)
    num_prices: Mapped[int] = mapped_column(Integer, default=0)
    has_coupon: Mapped[bool] = mapped_column(Boolean, default=False)
    # "Under ₹200" style ceiling, when explicitly stated (else NULL)
    price_threshold: Mapped[float | None] = mapped_column(Float)
    is_multi_deal: Mapped[bool] = mapped_column(Boolean, default=False)

    # merchant detection (deterministic, from known link domains only)
    primary_merchant_key: Mapped[str | None] = mapped_column(String(64))
    primary_merchant_confidence: Mapped[float | None] = mapped_column(Float)

    # overall extraction confidence (0..1), never a guess about meaning
    extraction_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    prices: Mapped[list["ExtractedPrice"]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )
    coupons: Mapped[list["ExtractedCoupon"]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )
    links: Mapped[list["ExtractedLink"]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )
    classifications: Mapped[list["PostClassification"]] = relationship(
        back_populates="normalized_post", cascade="all, delete-orphan"
    )


class ExtractedPrice(Base):
    __tablename__ = "extracted_prices"
    __table_args__ = (Index("ix_eprice_post", "normalized_post_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_post_id: Mapped[int] = mapped_column(
        ForeignKey("normalized_posts.id"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    raw_text: Mapped[str | None] = mapped_column(String(64))
    char_position: Mapped[int | None] = mapped_column(Integer)

    post: Mapped["NormalizedPost"] = relationship(back_populates="prices")


class ExtractedCoupon(Base):
    __tablename__ = "extracted_coupons"
    __table_args__ = (Index("ix_ecoupon_post", "normalized_post_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_post_id: Mapped[int] = mapped_column(
        ForeignKey("normalized_posts.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_text: Mapped[str | None] = mapped_column(String(128))

    post: Mapped["NormalizedPost"] = relationship(back_populates="coupons")


class ExtractedLink(Base):
    __tablename__ = "extracted_links"
    __table_args__ = (Index("ix_elink_post", "normalized_post_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_post_id: Mapped[int] = mapped_column(
        ForeignKey("normalized_posts.id"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255))
    is_shortlink: Mapped[bool] = mapped_column(Boolean, default=False)
    # merchant only when the domain is a KNOWN merchant domain; else NULL.
    # Shortlinks (grbn.in etc.) stay NULL until resolved by an enrichment pass —
    # we never guess the merchant behind an unresolved shortlink.
    merchant_key: Mapped[str | None] = mapped_column(String(64))
    resolved_url: Mapped[str | None] = mapped_column(String(1024))
    tracking_params: Mapped[dict | None] = mapped_column(JSON)

    post: Mapped["NormalizedPost"] = relationship(back_populates="links")
