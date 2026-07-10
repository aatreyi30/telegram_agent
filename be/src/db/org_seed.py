"""Seed the default Organization from .env and backfill existing channels.

Idempotent (like collection/merchants/registry.py:seed_merchants). Creates the
org (GrabOn by default), an owner user, and links existing Channel rows to it —
labelling each channel owned vs competitor from the configured handle lists.

The org's ``settings`` snapshot the affiliate config so provider resolution can
read per-org first and fall back to .env.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.settings import get_settings
from src.db.models import Channel
from src.db.models_org import Organization, User, UserRole
from src.logger import get_logger

logger = get_logger(__name__)


def _org_settings(s) -> dict:
    return {
        "affiliate_provider": s.affiliate_provider_name,
        "grabon_shortener_url": s.grabon_shortener_url,
        "grabon_amazon_tag": s.grabon_amazon_tag,
        "grabon_flipkart_params": s.grabon_flipkart_params,
        "grabon_shorten_all": s.grabon_shorten_all,
        # Global cron gate (not backed by .env, editable via PATCH /api/org only):
        # once a channel's competitor set is established, this stops
        # j_competitor_discover from auto-adding new ones. Defaults True so a
        # fresh install keeps discovering, matching today's behaviour.
        "auto_discover_competitors": True,
        "owned_channels": s.owned_channels,
        "competitor_channels": s.competitor_channels,
    }


def seed_org(session: Session) -> Organization:
    settings = get_settings()
    org = session.scalar(select(Organization).where(Organization.key == settings.org_key))
    if org is None:
        org = Organization(key=settings.org_key, name=settings.org_name,
                           affiliate_provider=settings.affiliate_provider_name,
                           settings=_org_settings(settings))
        session.add(org)
        session.flush()
        logger.info("[seed-org] created org '%s'", org.key)
    else:
        org.affiliate_provider = settings.affiliate_provider_name
        # Merge, DB-wins: .env-derived values only seed DEFAULTS / fill keys the org
        # doesn't have yet. Anything already set on the org (via the Settings UI /
        # PATCH /api/org — e.g. auto_discover_competitors, affiliate tags) is
        # PRESERVED. Previously this reassigned the whole dict from .env on every
        # startup, silently resetting UI-edited settings.
        merged = _org_settings(settings)
        merged.update(org.settings or {})
        org.settings = merged

    # one owner user with a login. Password from ADMIN_PASSWORD, else a random one
    # printed once (so a fresh install always has working credentials).
    from src.auth.security import hash_password

    owner = session.scalar(select(User).where(User.org_id == org.id, User.role == UserRole.OWNER))
    if owner is None:
        pw = settings.admin_password
        generated = None
        if not pw:
            import secrets
            pw = generated = secrets.token_urlsafe(9)
        session.add(User(org_id=org.id, name=f"{org.name} owner",
                         email=settings.admin_email, role=UserRole.OWNER,
                         password_hash=hash_password(pw)))
        if generated:
            logger.warning("[seed-org] created admin '%s' with generated password: %s "
                           "(set ADMIN_PASSWORD in .env to control this)",
                           settings.admin_email, generated)
    elif owner.password_hash is None and settings.admin_password:
        # existing structural user without a password -> set one from env
        owner.password_hash = hash_password(settings.admin_password)
        owner.email = owner.email or settings.admin_email

    # backfill channels: link to org + label owned/competitor from the handle lists
    owned = {h.lstrip("@").lower() for h in settings.owned_channels}
    for ch in session.scalars(select(Channel)):
        if ch.org_id is None:
            ch.org_id = org.id
        uname = (ch.username or "").lstrip("@").lower()
        ch.kind = "owned" if (uname in owned or not owned) else ch.kind or "owned"

    return org


def get_default_org(session: Session) -> Organization | None:
    return session.scalar(select(Organization).where(
        Organization.key == get_settings().org_key))
