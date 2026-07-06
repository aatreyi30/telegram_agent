"""Deal candidates from REAL observed data.

Until a live deal source (GrabCash API) is wired, deal candidates are extracted
from the channel's own collected posts — which carry REAL, reachable links
(grbn.in shortlinks), real themes, and real price tiers. No URLs are fabricated.

A loot/collection candidate mirrors how the channel actually posts them:
a theme ("<Category> Under ₹X"), a price tier, and several product+link items.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Post
from src.db.models_classification import PostClassification, PostTypeCluster
from src.db.models_normalization import NormalizedPost, SourceType
from src.services.processing.parser import parse_price_threshold

# "Product Name - https://grbn.in/xxxx"  (dash or en-dash)
_ITEM_RE = re.compile(r"^\s*(.+?)\s*[-–—]\s*(https?://\S+)\s*$")
_URL_ONLY = re.compile(r"^\s*(https?://\S+)\s*$")


@dataclass
class DealItem:
    name: str | None
    url: str


@dataclass
class Candidate:
    kind: str                       # "collection" | "single"
    theme: str | None               # real first line for collections
    price_threshold: float | None
    items: list[DealItem] = field(default_factory=list)
    cluster: str | None = None
    source_post_id: int | None = None


def _parse_items(text: str | None) -> list[DealItem]:
    """Pull 'Name - url' pairs (and bare urls) from a post body — real links only."""
    if not text:
        return []
    items: list[DealItem] = []
    for line in text.splitlines():
        m = _ITEM_RE.match(line)
        if m:
            name = m.group(1).strip()
            # ignore lines where the "name" is itself just a label/emoji noise
            items.append(DealItem(name=name or None, url=m.group(2).rstrip(").,")))
            continue
        u = _URL_ONLY.match(line)
        if u:
            items.append(DealItem(name=None, url=u.group(1).rstrip(").,")))
    return items


def observed_candidates(s: Session, limit: int = 20, window_days: int = 120) -> list[Candidate]:
    """Build real candidates from recent owned posts (newest first)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = s.execute(
        select(Post.id, Post.text, Post.posted_at, PostTypeCluster.descriptor)
        .join(NormalizedPost, NormalizedPost.source_id == Post.id)
        .join(PostClassification, PostClassification.normalized_post_id == NormalizedPost.id)
        .join(PostTypeCluster, PostTypeCluster.id == PostClassification.cluster_id)
        .where(NormalizedPost.source_type == SourceType.OWNED,
               Post.text.isnot(None))
        .order_by(Post.posted_at.desc())
        .limit(limit * 3)
    ).all()

    out: list[Candidate] = []
    for pid, text, posted_at, cluster in rows:
        items = _parse_items(text)
        if not items:
            continue
        theme = next((ln.strip() for ln in text.splitlines() if ln.strip()), None)
        threshold = parse_price_threshold(theme) or parse_price_threshold(text)
        kind = "collection" if len(items) >= 2 else "single"
        out.append(Candidate(kind=kind, theme=theme, price_threshold=threshold,
                             items=items, cluster=cluster, source_post_id=pid))
        if len(out) >= limit:
            break
    return out
