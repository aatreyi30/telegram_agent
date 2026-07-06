"""Selected-channel dependency — the multi-tenant isolation boundary.

Every data endpoint resolves which channel it operates on through this dependency,
which enforces that the channel belongs to the caller's organization. A request can
never read another org's channel: an explicit ?channel_id outside the org 404s, and
the default is the org's own first channel.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Query
from sqlalchemy import select

from src.db.models import Channel
from src.db.session import session_scope
from src.shared.deps import current_user


def _org_owned_channel_ids(org_id: int | None) -> list[int]:
    with session_scope() as s:
        q = select(Channel.id).where(Channel.kind == "owned").order_by(Channel.id)
        if org_id is not None:
            q = q.where(Channel.org_id == org_id)
        return list(s.scalars(q).all())


def selected_channel_id(channel_id: int | None = Query(default=None),
                        user: dict = Depends(current_user)) -> int | None:
    """Resolve + authorize the channel for this request.

    - explicit ?channel_id must be one of the caller's org channels (else 404)
    - no param → the org's first channel
    - None if the org has no channels yet (reads then return empty, not an error)."""
    allowed = _org_owned_channel_ids(user.get("org_id"))
    if channel_id is not None:
        if channel_id not in allowed:
            raise HTTPException(status_code=404, detail="Channel not found")
        return channel_id
    return allowed[0] if allowed else None
