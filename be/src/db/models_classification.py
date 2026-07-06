"""Phase 3 storage — learned post-type classification.

Post types are NOT hardcoded (RULE 3). They are discovered by clustering the
data-derived features produced in Phase 2 (link count, price stats, coupon
presence, multi-deal, emoji, CTA, merchant-known). Each cluster is described by
its own feature signature — the descriptor is derived from data, not a keyword
rule. Semantic naming of a cluster ("Loot"/"Coupon"/…) is a later evidence-based
step; nothing here assigns meaning by matching words.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin

CLASSIFICATION_VERSION = 1


class PostTypeCluster(Base, TimestampMixin):
    """A learned post-type cluster (one row per cluster per fit run)."""

    __tablename__ = "post_type_clusters"
    __table_args__ = (
        UniqueConstraint("classification_version", "cluster_index", name="uq_cluster_ver_idx"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classification_version: Mapped[int] = mapped_column(Integer, default=CLASSIFICATION_VERSION)
    cluster_index: Mapped[int] = mapped_column(Integer, nullable=False)
    size: Mapped[int] = mapped_column(Integer, default=0)

    # standardized centroid + human-readable, DATA-DERIVED description
    centroid: Mapped[dict] = mapped_column(JSON)          # feature -> standardized value
    feature_means: Mapped[dict] = mapped_column(JSON)     # feature -> raw mean
    descriptor: Mapped[str | None] = mapped_column(String(255))
    fitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    classifications: Mapped[list["PostClassification"]] = relationship(
        back_populates="cluster"
    )


class PostClassification(Base):
    """Assignment of one normalized post to a learned cluster."""

    __tablename__ = "post_classifications"
    __table_args__ = (
        UniqueConstraint("normalized_post_id", name="uq_classification_post"),
        Index("ix_classification_cluster", "cluster_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_post_id: Mapped[int] = mapped_column(
        ForeignKey("normalized_posts.id"), nullable=False
    )
    cluster_id: Mapped[int] = mapped_column(ForeignKey("post_type_clusters.id"), nullable=False)
    classification_version: Mapped[int] = mapped_column(Integer, default=CLASSIFICATION_VERSION)
    # confidence = 1 - (distance to own centroid / distance to 2nd-nearest); higher
    # means the post sits clearly inside its cluster. Data-derived, not a guess.
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    classified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    cluster: Mapped["PostTypeCluster"] = relationship(back_populates="classifications")
