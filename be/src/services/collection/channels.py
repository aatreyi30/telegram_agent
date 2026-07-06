"""Channel resolution for the pipeline.

The collection/analysis jobs used to read the owned channel list straight from
``settings.owned_channels`` (the .env constant — single-tenant, GrabOn only). Now
they resolve the list from the ``channels`` table so each org's channels drive the
pipeline. The .env list is kept only as a fallback for a brand-new install whose
``channels`` table is still empty (first boot before the first collection).
"""

from __future__ import annotations

from sqlalchemy import select

from src.config.settings import get_settings
from src.db.models import Channel
from src.db.session import session_scope


def normalize_handle(raw: str) -> str:
    """'@Foo', 'https://t.me/Foo', 't.me/Foo/123' -> 'Foo'. Empty on junk."""
    h = (raw or "").strip()
    for prefix in ("https://", "http://"):
        if h.lower().startswith(prefix):
            h = h[len(prefix):]
    if h.lower().startswith("t.me/"):
        h = h[len("t.me/"):]
    h = h.lstrip("@").strip("/")
    if "/" in h:                       # t.me/Foo/123 -> Foo
        h = h.split("/", 1)[0]
    return h


def owned_handles() -> list[str]:
    """@usernames of every owned channel across all orgs (DB is source of truth);
    falls back to the .env OWNED_CHANNELS on an empty table."""
    with session_scope() as s:
        rows = s.scalars(
            select(Channel.username).where(
                Channel.kind == "owned", Channel.username.isnot(None))
        ).all()
    handles = [h for h in rows if h]
    return handles or get_settings().owned_channels
