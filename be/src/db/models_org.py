"""Organization / User model — structural multi-tenancy (no auth this pass).

The platform is multi-tenant: an Organization owns channels, configures its own
affiliate provider + credentials, and has users. This mirrors the GrabOn affiliate
spec, which is explicitly org-scoped ("when Organization = GrabOn …"). Provider
resolution reads the org's settings first, falling back to .env defaults — so no
client-specific logic lives in the core.

No passwords/login yet: User rows organize ownership and roles; a login surface can
be layered on later without reshaping these tables.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin


class UserRole:
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("key", name="uq_org_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)      # e.g. "grabon"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    affiliate_provider: Mapped[str | None] = mapped_column(String(32))  # "grabon" | "generic" | ...
    # per-org config overrides (shortener URL, amazon tag, flipkart params, owned handle,
    # competitor handles, shorten_all flag, …). Read before .env defaults.
    settings: Mapped[dict | None] = mapped_column(JSON)

    users: Mapped[list["User"]] = relationship(back_populates="org")


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("org_id", "email", name="uq_user_org_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default=UserRole.OWNER)
    password_hash: Mapped[str | None] = mapped_column(String(255))  # pbkdf2 (see auth/security)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    org: Mapped["Organization"] = relationship(back_populates="users")
