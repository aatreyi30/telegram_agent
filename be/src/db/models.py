"""ORM models — the storage layer for the whole system.

Scope note (STRICT build order): this file defines the **ingestion + storage**
tables that Phase 1 populates, plus the collection-infrastructure tables
(raw snapshots, jobs, events). Intelligence tables (post_classification,
templates, learning_events, growth_recommendations, campaigns) are declared as
lightweight forward-looking shells so the schema in Data_Model_Final is
complete and stable, but they are NOT written to by any Phase-1 collector.

Global rules honoured here:
  * RULE 1 (no hallucination): every field that must be *derived* rather than
    *observed* defaults to NULL / UNKNOWN. Nothing is guessed.
  * RULE 3 (no hard-coding): categories, merchants (as business entities),
    templates and CTAs are DATA rows, never enum values in code. The only
    enums are system constraints (job status, source access status, etc.).
  * Traceability: ingestion rows link back to an immutable RawSnapshot.
  * Versioning: dedup via content hashes; historical versions preserved.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
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

# Channel has a ForeignKey to organizations; importing the org models here
# guarantees that table is registered on Base.metadata whenever this module is
# loaded in isolation (e.g. a collector that only imports Channel), so SQLAlchemy
# can always resolve the FK. No circular import (models_org imports only base).
from src.db import models_org  # noqa: F401,E402
from src.db.models_growth_snapshot import ParticipantSnapshot  # noqa: F401,E402 — register on metadata

# --------------------------------------------------------------------------- #
# System-level constant vocabularies (constraints, NOT learned categories)
# --------------------------------------------------------------------------- #

UNKNOWN = "unknown"


class SourceAccessStatus:
    """Whether a data source can actually be collected (Data Validation Matrix)."""

    AVAILABLE = "available"      # confirmed collectable
    PARTIAL = "partial"          # collectable with caveats / manual input
    BLOCKED = "blocked"          # confirmed NOT collectable — never fabricate
    UNKNOWN = "unknown"


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRY = "retry"
    COMPLETED = "completed"
    SKIPPED = "skipped"          # source unavailable -> skipped, not failed


class CollectionType:
    INITIAL = "initial"
    INCREMENTAL = "incremental"
    ANALYTICS = "analytics"
    METRIC_SNAPSHOT = "metric_snapshot"
    MANUAL = "manual"


# --------------------------------------------------------------------------- #
# Collection infrastructure
# --------------------------------------------------------------------------- #


class RawSnapshot(Base, TimestampMixin):
    """Immutable pointer to a raw collected payload.

    Design principle (spec 08): *never modify raw collected data*. The actual
    bytes are written to a file on disk (or object storage); this row records
    where it lives, its sha256, and which job produced it, so any structured
    record can be traced back to the exact source payload.
    """

    __tablename__ = "raw_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "telegram_owned"
    source_ref: Mapped[str | None] = mapped_column(String(255))       # channel/url/etc.
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(64), default="application/json")
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("collection_jobs.id"))

    __table_args__ = (
        Index("ix_raw_snapshots_source_ref", "source", "source_ref"),
    )


class CollectionJob(Base, TimestampMixin):
    """One unit of collection work (spec 08 job lifecycle + observability)."""

    __tablename__ = "collection_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)   # collector name
    collection_type: Mapped[str] = mapped_column(String(32), default=CollectionType.INCREMENTAL)
    target: Mapped[str | None] = mapped_column(String(255))             # channel/merchant/etc.
    priority: Mapped[int] = mapped_column(Integer, default=100)         # lower = sooner
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.QUEUED, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    records_added: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0)

    error_message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON)  # job-specific args


class CollectionEvent(Base):
    """Durable log of emitted events (PostCollected, MerchantUpdated, ...).

    Intelligence engines (later phases) subscribe to these instead of polling
    external systems. Persisting them lets a restarted subscriber catch up.
    """

    __tablename__ = "collection_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("collection_jobs.id"))
    data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


# --------------------------------------------------------------------------- #
# Owned channels
# --------------------------------------------------------------------------- #


class Channel(Base, TimestampMixin):
    """An owned Telegram channel (operator is admin). Source of truth: Telegram."""

    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_channel_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    # multi-tenancy: which org this channel belongs to (nullable; backfilled by seed-org)
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="owned")  # owned | competitor
    # pending  = added via the UI, Telegram id not resolved yet (tg_channel_id is a
    #            negative placeholder until an authed client resolves the @username);
    # active   = resolved / collected at least once.
    status: Mapped[str] = mapped_column(String(16), default="active")
    username: Mapped[str | None] = mapped_column(String(128), index=True)
    title: Mapped[str | None] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(16), default=UNKNOWN)
    participants_count: Mapped[int | None] = mapped_column(Integer)  # last observed
    can_view_stats: Mapped[bool] = mapped_column(Boolean, default=False)
    stats_dc: Mapped[int | None] = mapped_column(Integer)  # MTProto stats datacenter
    # last time stats.getBroadcastStats was synced for this channel (rate-limited to
    # once/IST-day — see telegram_owned.py::_collect_broadcast_stats)
    stats_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict | None] = mapped_column(JSON)

    first_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_id: Mapped[int | None] = mapped_column(BigInteger)  # incremental cursor

    posts: Mapped[list["Post"]] = relationship(back_populates="channel")


class Post(Base, TimestampMixin):
    """A raw message from an owned channel.

    Phase 1 stores only *observed* facts. Derived fields (post type, merchant,
    category, extracted deal) are added by the Normalization/Classification
    engines in Phase 2+ and are intentionally left NULL / UNKNOWN here.
    """

    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("channel_id", "tg_message_id", name="uq_post_channel_msg"),
        Index("ix_posts_posted_at", "posted_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    tg_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    text: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)

    # observed media / link facts (not yet interpreted)
    has_media: Mapped[bool] = mapped_column(Boolean, default=False)
    media_type: Mapped[str | None] = mapped_column(String(32))
    links: Mapped[list | None] = mapped_column(JSON)      # raw URLs found in message
    grouped_id: Mapped[int | None] = mapped_column(BigInteger)  # album grouping

    # latest observed counters (time-series lives in PostMetricSnapshot)
    views: Mapped[int | None] = mapped_column(Integer)
    forwards: Mapped[int | None] = mapped_column(Integer)
    reactions_total: Mapped[int | None] = mapped_column(Integer)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("raw_snapshots.id"))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    channel: Mapped["Channel"] = relationship(back_populates="posts")
    metric_snapshots: Mapped[list["PostMetricSnapshot"]] = relationship(
        back_populates="post"
    )


class PostMetricSnapshot(Base):
    """Time-series of a post's counters.

    Critical per Feature 7 (Data Validation Matrix): view velocity is NOT
    retroactively available. We reconstruct it by snapshotting each post at
    configured offsets (T+1h, T+4h, T+24h, ...). Each row is one observation.
    """

    __tablename__ = "post_metric_snapshots"
    __table_args__ = (
        Index("ix_pms_post_time", "post_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    age_hours: Mapped[float | None] = mapped_column(Float)  # hours since posted_at
    views: Mapped[int | None] = mapped_column(Integer)
    forwards: Mapped[int | None] = mapped_column(Integer)
    reactions_total: Mapped[int | None] = mapped_column(Integer)
    reactions_breakdown: Mapped[dict | None] = mapped_column(JSON)  # emoji -> count

    post: Mapped["Post"] = relationship(back_populates="metric_snapshots")


# --------------------------------------------------------------------------- #
# Competitors (public, OBSERVED only via t.me/s)
# --------------------------------------------------------------------------- #


class Competitor(Base, TimestampMixin):
    """A public competitor channel monitored via t.me/s (no auth, scrape).

    ``category`` is ``"platform"`` (has own coupon website + Telegram, e.g. Grabon)
    or ``"channel"`` (Telegram-only deal channel). Set during discovery via web
    search; ``None`` means not yet classified.
    """

    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    subscribers_text: Mapped[str | None] = mapped_column(String(64))  # as shown, e.g. "1.2K"
    access_status: Mapped[str] = mapped_column(
        String(16), default=SourceAccessStatus.AVAILABLE
    )
    discovered_via: Mapped[str | None] = mapped_column(String(64))
    category: Mapped[str | None] = mapped_column(String(16))  # "platform" | "channel"
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_confidence: Mapped[float | None] = mapped_column(Float)
    verified_by: Mapped[str | None] = mapped_column(String(16))  # heuristic|ai|manual

    posts: Mapped[list["CompetitorPost"]] = relationship(back_populates="competitor")


class CompetitorPost(Base, TimestampMixin):
    """An observed competitor post. Rich fields (views, forwards, reactions)
    are populated when collected via Telethon (Telegram API) — the t.me/s
    web-preview fallback only exposes views approximately.
    """

    __tablename__ = "competitor_posts"
    __table_args__ = (
        UniqueConstraint("competitor_id", "tg_message_id", name="uq_comp_post"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), nullable=False)
    tg_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    text: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    links: Mapped[list | None] = mapped_column(JSON)
    has_media: Mapped[bool] = mapped_column(Boolean, default=False)

    # Populated natively when collected via Telethon (Telegram API).
    # The t.me/s fallback populates views_text and views (best-effort parse).
    views_text: Mapped[str | None] = mapped_column(String(32))
    views: Mapped[int | None] = mapped_column(Integer)
    forwards: Mapped[int | None] = mapped_column(Integer)
    reactions_total: Mapped[int | None] = mapped_column(Integer)

    raw_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("raw_snapshots.id"))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    competitor: Mapped["Competitor"] = relationship(back_populates="posts")


# --------------------------------------------------------------------------- #
# Merchants & products (buildable merchants only)
# --------------------------------------------------------------------------- #


class Merchant(Base, TimestampMixin):
    """A merchant registry row.

    Merchants exist as DATA, not code enums (RULE 3). ``access_status`` records
    the Data Validation Matrix verdict so downstream layers know when product
    data is genuinely unobtainable (BLOCKED) versus needing operator input
    (PARTIAL). BLOCKED merchants are seeded so the system can *represent* them
    without ever *fabricating* their data.
    """

    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # slug
    display_name: Mapped[str] = mapped_column(String(128))
    domains: Mapped[list | None] = mapped_column(JSON)  # url domains for detection
    collector: Mapped[str | None] = mapped_column(String(64))  # collector id or None
    access_status: Mapped[str] = mapped_column(
        String(16), default=SourceAccessStatus.UNKNOWN
    )
    access_notes: Mapped[str | None] = mapped_column(Text)  # why blocked/partial

    products: Mapped[list["MerchantProduct"]] = relationship(back_populates="merchant")


class MerchantProduct(Base, TimestampMixin):
    """Product data fetched from a buildable merchant source."""

    __tablename__ = "merchant_products"
    __table_args__ = (
        UniqueConstraint("merchant_id", "external_id", name="uq_merchant_product"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128))  # ASIN / FSN / handle
    title: Mapped[str | None] = mapped_column(String(1024))
    brand: Mapped[str | None] = mapped_column(String(255))
    category_text: Mapped[str | None] = mapped_column(String(255))  # merchant-provided
    product_url: Mapped[str | None] = mapped_column(String(1024))
    image_url: Mapped[str | None] = mapped_column(String(1024))

    current_price: Mapped[float | None] = mapped_column(Float)
    mrp: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    availability: Mapped[str | None] = mapped_column(String(32))  # in_stock/out/unknown

    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("raw_snapshots.id"))

    merchant: Mapped["Merchant"] = relationship(back_populates="products")
    price_history: Mapped[list["ProductPriceSnapshot"]] = relationship(
        back_populates="product"
    )


class ProductPriceSnapshot(Base):
    """Self-accumulated price history (no external history API exists — see
    Data Validation Matrix Feature 4). Meaningful only after ~90 days."""

    __tablename__ = "product_price_snapshots"
    __table_args__ = (Index("ix_pps_product_time", "product_id", "captured_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("merchant_products.id"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_price: Mapped[float | None] = mapped_column(Float)
    mrp: Mapped[float | None] = mapped_column(Float)
    availability: Mapped[str | None] = mapped_column(String(32))

    product: Mapped["MerchantProduct"] = relationship(back_populates="price_history")


# --------------------------------------------------------------------------- #
# Affiliate links (PARTIAL: link map only; click data not auto-fetchable)
# --------------------------------------------------------------------------- #


class AffiliateLink(Base, TimestampMixin):
    """Maps a short/affiliate URL to its resolved destination.

    Click/conversion counts are NOT programmatically available (Revenue Data
    Gap, Data Validation Matrix §5). ``clicks`` stays NULL unless an operator
    manually supplies portal data — we never estimate it.
    """

    __tablename__ = "affiliate_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    short_url: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    resolved_url: Mapped[str | None] = mapped_column(String(1024))
    domain: Mapped[str | None] = mapped_column(String(255))
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"))
    tracking_params: Mapped[dict | None] = mapped_column(JSON)
    http_status: Mapped[int | None] = mapped_column(Integer)  # last checked
    is_broken: Mapped[bool | None] = mapped_column(Boolean)     # None = unchecked
    clicks: Mapped[int | None] = mapped_column(Integer)         # UNKNOWN unless manual
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
