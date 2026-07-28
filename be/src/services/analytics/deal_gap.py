"""Competitor deal-gap — per-category share of posts, owned vs tracked
competitors, over one window. Flags categories where competitors clearly
over-index relative to us (including categories we're entirely absent from).

Deterministic and honest about sample size: a category only appears when the
COMPETITOR side has a real sample (MIN_COMPETITOR_N) — a category no
competitor posts about isn't a "gap", it's not a signal at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import CompetitorPost, Post
from src.db.models_normalization import NormalizedPost, SourceType

# A category needs at least this many categorized competitor posts in the
# window before it's reported at all (a single stray post isn't a trend).
MIN_COMPETITOR_N = 5

# Minimum (competitor_share - owned_share) percentage-point gap to flag a
# category as "competitors over-index here" — small gaps are noise.
GAP_THRESHOLD = 0.05


def _category_counts(s: Session, source_type: str, model, cutoff) -> dict[str, int]:
    q = (
        select(NormalizedPost.category, func.count())
        .select_from(NormalizedPost)
        .join(model, NormalizedPost.source_id == model.id)
        .where(NormalizedPost.source_type == source_type, NormalizedPost.category.isnot(None))
    )
    if cutoff is not None:
        q = q.where(model.posted_at >= cutoff)
    q = q.group_by(NormalizedPost.category)
    return dict(s.execute(q).all())


def _all_posts_count(s: Session, source_type: str, model, cutoff) -> int:
    """Every normalized post for this source in the window, categorized or
    not — the denominator `_category_counts` needs to report honest coverage
    instead of silently sharing categorized-post totals as "share of posts"."""
    q = (
        select(func.count())
        .select_from(NormalizedPost)
        .join(model, NormalizedPost.source_id == model.id)
        .where(NormalizedPost.source_type == source_type)
    )
    if cutoff is not None:
        q = q.where(model.posted_at >= cutoff)
    return s.scalar(q) or 0


def compute(s: Session, window_days: int = 30) -> dict:
    """Per-category deal-gap over the last ``window_days`` (None = all-time)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)) if window_days else None

    owned_counts = _category_counts(s, SourceType.OWNED, Post, cutoff)
    comp_counts = _category_counts(s, SourceType.COMPETITOR, CompetitorPost, cutoff)

    # `owned_total`/`comp_total` (categorized-post totals) remain the
    # denominators for `owned_share`/`competitor_share` in `rows` below — that
    # shape is already consumed by the frontend. The two sides have
    # systematically different categorization coverage: `parser.infer_category`
    # is a keyword match against the post's OWN text (never guessed from the
    # merchant), and competitor posts are frequently forwards with sparse,
    # low-keyword captions, so a smaller share of them hit any category
    # keyword than owned posts (written with fuller, deliberately descriptive
    # copy). That leaves the shares comparing differently-sized populations.
    # Report each side's categorized/total coverage explicitly so a consumer
    # can see and correct for that bias instead of trusting "share of posts"
    # at face value.
    owned_total = sum(owned_counts.values())
    comp_total = sum(comp_counts.values())
    owned_all = _all_posts_count(s, SourceType.OWNED, Post, cutoff)
    comp_all = _all_posts_count(s, SourceType.COMPETITOR, CompetitorPost, cutoff)

    rows = []
    for cat, comp_n in comp_counts.items():
        if comp_n < MIN_COMPETITOR_N:
            continue
        owned_n = owned_counts.get(cat, 0)
        owned_share = round(owned_n / owned_total, 4) if owned_total else 0.0
        comp_share = round(comp_n / comp_total, 4) if comp_total else 0.0
        gap = round(comp_share - owned_share, 4)
        rows.append({
            "category": cat,
            "owned_n": owned_n,
            "owned_share": owned_share,
            "competitor_n": comp_n,
            "competitor_share": comp_share,
            "gap": gap,
            "over_indexed_by_competitors": gap >= GAP_THRESHOLD,
        })
    rows.sort(key=lambda r: r["gap"], reverse=True)

    return {
        "window_days": window_days,
        "min_competitor_n": MIN_COMPETITOR_N,
        "gap_threshold": GAP_THRESHOLD,
        "rows": rows,
        "owned_coverage": {"categorized": owned_total, "total": owned_all},
        "competitor_coverage": {"categorized": comp_total, "total": comp_all},
    }
