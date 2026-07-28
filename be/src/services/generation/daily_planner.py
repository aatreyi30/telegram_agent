"""Recently-used-URL guard, shared by the just-in-time filler.

The old deterministic day-planner (``build_and_schedule_day``) was retired when the
AI plan + just-in-time fill path (``services/generation/jit_fill.py``) took over
scheduling. Only this dedup helper survives — it stops a deal used in the last few
days from being posted again.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models_generation import EnrichedDeal, GeneratedPost


def recently_used_urls(s: Session, days: int = 3) -> set[str]:
    """Everything that identifies a deal already used in the last ``days`` — the source's
    own deal id AND its URLs — so we never repeat one.

    The ids are the real key: `EnrichedDeal.deal_id` is now the source's `external_id`
    (see `enrichment.py`), which is stable across price moves. The URLs stay in the set
    because matching them is free and covers the fallback case where a deal carries no
    source id, plus rows written before the id switch. Callers treat the result as an
    opaque "already used" set and test every identifier they have — see
    `jit_fill._pick_fresh`."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deal_ids: set[str] = set()
    for gp in s.scalars(select(GeneratedPost).where(GeneratedPost.generated_at >= cutoff)):
        for d in (gp.deal_ids or []):
            deal_ids.add(d)
    if not deal_ids:
        return set()
    urls: set[str] = set(deal_ids)
    for e in s.scalars(select(EnrichedDeal).where(EnrichedDeal.deal_id.in_(deal_ids))):
        if e.url:
            urls.add(e.url)
        if e.clean_url:
            urls.add(e.clean_url)
    return urls
