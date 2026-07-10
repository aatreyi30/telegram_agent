"""Phase 0.2 — persist AI outputs instead of dropping the returned string.

``record_ai_output`` is the one place every AI-generated artifact (briefings,
coach answers, the weekly retro narrative) gets written to the ``ai_outputs``
table, so the operator (and later, the retro/factcheck loop) has a durable
record of what the AI said, when, and against which grounding context.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from src.db.models_ai_output import AIOutput
from src.db.session import session_scope


def record_ai_output(
    kind: str,
    content: str | None,
    model: str,
    *,
    channel_id: int | None = None,
    context: dict | None = None,
    session: Session | None = None,
) -> None:
    """Best-effort persist. Never raises into the caller's happy path; a missing
    ``content`` (AI unavailable / skipped) is simply a no-op, not an error.

    Pass ``session`` when the caller already has an open, uncommitted write
    session (e.g. ``retro.py::build_weekly_retro``, which is handed an outer
    session mid-transaction) so this adds to that same transaction instead of
    opening a second writer connection -- on SQLite, a second connection
    trying to write while the first's transaction is still uncommitted blocks
    on the first's write lock and raises ``database is locked`` once
    ``busy_timeout`` elapses. Callers with no open session (the common case --
    briefings/coach answers) keep getting their own short-lived transaction.
    """
    if not content:
        return
    h = (
        hashlib.sha256(json.dumps(context, sort_keys=True, default=str).encode()).hexdigest()
        if context else None
    )
    row = AIOutput(kind=kind, channel_id=channel_id, content=content, model=model,
                   prompt_context_hash=h)
    if session is not None:
        session.add(row)
        return
    with session_scope() as s:
        s.add(row)
