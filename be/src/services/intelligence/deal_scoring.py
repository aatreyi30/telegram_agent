"""Phase 3.2 -- DealScoringEngine: audience-aware, explainable deal score.

Runs on a schedule (job ``deal_ranking``, every ``cadences.DEAL_RANKING_MIN``
minutes) and writes one ``DealScore`` HISTORY row per active deal per run
(``models_deal_score.py``). This COEXISTS with ``DealRanker``
(``generation/ranking.py``), which still drives which deals get selected into
a draft at generation time -- nothing here reads/writes
``EnrichedDeal.rank_score``/``score_breakdown``. ``DealScoringEngine`` instead
feeds ``/api/deals/scored`` and the planner's ``scored_deals`` context
(Section 3.3 of upgrade.md).

    score = 100 * ( 0.25*discount_depth   + 0.20*audience_affinity
                  + 0.15*freshness        + 0.15*time_fit
                  + 0.15*price_credibility + 0.10*scarcity_of_coverage )

Every component is normalized to [0,1] and stored verbatim in ``components``,
so ``round(100 * sum(WEIGHTS[k] * components[k] for k in WEIGHTS), 3) ==
score`` always holds exactly (asserted in tests) -- the "explainable" part of
Section 3.2.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import CompetitorPost, MerchantProduct, Post
from src.db.models_deal_score import DealScore
from src.db.models_generation import DealValidity, EnrichedDeal
from src.db.models_normalization import NormalizedPost, SourceType
from src.db.models_prediction import PostOutcome
from src.services.analytics import engagement as _engagement
from src.services.analytics.periods import to_ist
from src.services.analytics.prediction import hour_bucket
from src.logger import get_logger

logger = get_logger(__name__)

# --------------------------------------------------------------------------- #
# The formula (Section 3.2, exact) -- weights live ONLY here.
# --------------------------------------------------------------------------- #
WEIGHTS: dict[str, float] = {
    "discount_depth": 0.25,
    "audience_affinity": 0.20,
    "freshness": 0.15,
    "time_fit": 0.15,
    "price_credibility": 0.15,
    "scarcity_of_coverage": 0.10,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "DealScoringEngine.WEIGHTS must sum to 1.0"

DISCOUNT_DEPTH_CAP_PCT = 60.0            # discount_depth = min(1, discount_percent/60)
FAKE_MRP_OVERSHOOT_PCT = 0.05            # MerchantProduct.current_price > deal price * 1.05 -> fake MRP
FAKE_MRP_SCORE_CAP = 0.2
FRESHNESS_HALF_LIFE_HOURS = 24.0         # freshness = exp(-hours_since_first_seen/24)
SCARCITY_WINDOW_HOURS = 24
SCARCITY_DIVISOR = 5.0
PRICE_CRED_FRESH_HOURS = 2.0              # <2h -> 1.0
PRICE_CRED_STALE_HOURS = 12.0             # <12h -> 0.7, else 0.3 (unvalidated)
UNKNOWN_AFFINITY = 0.5
UNKNOWN_SCARCITY = 0.5
UNKNOWN_TIME_FIT = 0.5
TIME_FIT_WINDOW_HOURS = 6.0               # within next 6h -> 1.0
TIME_FIT_FALLOFF_HOURS = 24.0             # linear falloff to 0 by +24h
MIN_HOUR_BUCKET_SAMPLES = 5               # a bucket needs >=5 posts to be trusted (mirrors retro.py)


def _aware_utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on read-back; we always store UTC, so treat naive
    datetimes as UTC (mirrors the ``_aware``/``_aware_utc`` helper used across
    ``generation/revalidate.py``, ``analytics/engagement.py``, etc.)."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Component functions -- each pure and independently testable.
# --------------------------------------------------------------------------- #
def discount_depth(deal: EnrichedDeal, product: MerchantProduct | None) -> float:
    """``min(1, discount_percent/60)``, capped at 0.2 when the correlated
    ``MerchantProduct.current_price`` shows the claimed deal price understates
    the real current price by >5% (fake-MRP protection, Section 3.2)."""
    d = deal.discount_percent or 0.0
    base = min(1.0, max(0.0, d) / DISCOUNT_DEPTH_CAP_PCT)
    if (
        product is not None
        and product.current_price is not None
        and deal.current_price
        and product.current_price > deal.current_price * (1 + FAKE_MRP_OVERSHOOT_PCT)
    ):
        return round(min(base, FAKE_MRP_SCORE_CAP), 4)
    return round(base, 4)


def freshness(deal: EnrichedDeal, *, now: datetime | None = None) -> float:
    """``exp(-hours_since_first_seen/24)`` -- first-seen is the deal's
    ``created_at`` (earliest timestamp ``EnrichedDeal`` carries)."""
    first_seen = _aware_utc(deal.created_at)
    if first_seen is None:
        return UNKNOWN_TIME_FIT  # never fabricate an age we don't have
    now = now or datetime.now(timezone.utc)
    hours = max((now - first_seen).total_seconds() / 3600.0, 0.0)
    return round(math.exp(-hours / FRESHNESS_HALF_LIFE_HOURS), 4)


def price_credibility(deal: EnrichedDeal, product: MerchantProduct | None, *, now: datetime | None = None) -> float:
    """1.0 if revalidated in-stock <2h ago; 0.7 <12h; 0.3 unvalidated (no
    correlated product, or never verified); 0.0 if the last check shows the
    product is out of stock (reuses the same ``MerchantProduct.availability``
    signal as ``generation/revalidate.py``)."""
    if product is None:
        return 0.3
    if product.availability and product.availability.lower() not in ("in_stock", "unknown"):
        return 0.0  # last check failed
    verified_at = _aware_utc(product.last_verified_at)
    if verified_at is None:
        return 0.3
    now = now or datetime.now(timezone.utc)
    age_hours = max((now - verified_at).total_seconds() / 3600.0, 0.0)
    if age_hours < PRICE_CRED_FRESH_HOURS:
        return 1.0
    if age_hours < PRICE_CRED_STALE_HOURS:
        return 0.7
    return 0.3


def _bucket_start_hour(bucket: str) -> int:
    """"00-02" -> 0, "03-05" -> 3, ... matches ``prediction.hour_bucket``'s labels."""
    return int(bucket.split("-", 1)[0])


def time_fit(best_bucket: str | None, *, now_ist_hour: int) -> float:
    """1.0 if ``best_bucket`` starts within the next 6h from ``now_ist_hour``;
    linear falloff to 0.0 by +24h; 0.5 when there's no reliable best bucket
    (Section 3.2)."""
    if best_bucket is None:
        return UNKNOWN_TIME_FIT
    start = _bucket_start_hour(best_bucket)
    hours_until = (start - now_ist_hour) % 24
    if hours_until <= TIME_FIT_WINDOW_HOURS:
        return 1.0
    span = TIME_FIT_FALLOFF_HOURS - TIME_FIT_WINDOW_HOURS
    return round(max(0.0, 1.0 - (hours_until - TIME_FIT_WINDOW_HOURS) / span), 4)


def scarcity_of_coverage(merchant_key: str | None, coverage: dict[str, int]) -> float:
    """``1 - min(1, competitor_posts_matching_merchant_last_24h / 5)``. Unknown
    merchant -> 0.5 (neutral; never assume perfect exclusivity for a merchant
    we can't even attribute)."""
    if not merchant_key:
        return UNKNOWN_SCARCITY
    n = coverage.get(merchant_key, 0)
    return round(1.0 - min(1.0, n / SCARCITY_DIVISOR), 4)


# --------------------------------------------------------------------------- #
# Per-run context -- the DB reads shared across every deal in one scoring pass.
# --------------------------------------------------------------------------- #
@dataclass
class _ScoringContext:
    now: datetime
    affinity: dict[str, float] = field(default_factory=dict)          # merchant_key -> mean engagement_score
    coverage: dict[str, int] = field(default_factory=dict)            # merchant_key -> competitor posts/24h
    best_bucket: str | None = None                                    # best owned-post engagement hour bucket
    products_by_url: dict[str, MerchantProduct] = field(default_factory=dict)


def _merchant_affinity_map(s: Session) -> dict[str, float]:
    """Mean ``engagement_score`` (Phase 2.0, ``engagement.py`` -- reused, not
    re-derived) of our own last-``WINDOW_DAYS``-day posts, per
    ``NormalizedPost.primary_merchant_key`` -- Section 3.2's audience_affinity."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=_engagement.WINDOW_DAYS)
    rows = s.execute(
        select(NormalizedPost.primary_merchant_key, PostOutcome.engagement_score)
        .select_from(PostOutcome)
        .join(Post, Post.id == PostOutcome.post_id)
        .join(NormalizedPost, (NormalizedPost.source_id == Post.id) & (NormalizedPost.source_type == SourceType.OWNED))
        .where(
            Post.posted_at.isnot(None),
            Post.posted_at >= cutoff,
            NormalizedPost.primary_merchant_key.isnot(None),
            PostOutcome.engagement_score.isnot(None),
        )
    ).all()
    by_merchant: dict[str, list[float]] = defaultdict(list)
    for merchant_key, score in rows:
        by_merchant[merchant_key].append(score)
    return {k: statistics.fmean(v) for k, v in by_merchant.items() if v}


def _competitor_coverage_map(s: Session, *, hours: int = SCARCITY_WINDOW_HOURS) -> dict[str, int]:
    """Competitor posts matching each ``merchant_key`` in the last ``hours``
    (proxy match -- exact product match needs Phase 4, out of scope)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = s.execute(
        select(NormalizedPost.primary_merchant_key, NormalizedPost.id)
        .select_from(NormalizedPost)
        .join(CompetitorPost, CompetitorPost.id == NormalizedPost.source_id)
        .where(
            NormalizedPost.source_type == SourceType.COMPETITOR,
            NormalizedPost.primary_merchant_key.isnot(None),
            CompetitorPost.posted_at.isnot(None),
            CompetitorPost.posted_at >= cutoff,
        )
    ).all()
    counts: dict[str, int] = defaultdict(int)
    for merchant_key, _id in rows:
        counts[merchant_key] += 1
    return dict(counts)


def _best_hour_bucket(s: Session, *, window_days: int = _engagement.WINDOW_DAYS,
                       min_samples: int = MIN_HOUR_BUCKET_SAMPLES) -> str | None:
    """Best owned-post engagement hour bucket over the trailing window.

    APPROXIMATION NOTE: Section 3.2 specifies "category's best engagement hour
    bucket", but ``EnrichedDeal.category`` is explicitly not-yet-extracted
    (always UNKNOWN in practice -- see ``models_generation.py``), so there is
    no reliable per-category signal to correlate a deal against yet. This
    falls back to the channel-wide best hour bucket instead (same computation
    as ``retro.py::_engagement_summary``'s ``best_hour_bucket``, just scoped to
    this scoring run's own window rather than one retro week) -- honest given
    the current data, and trivially upgradeable to per-category once category
    extraction exists.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = s.execute(
        select(Post.posted_at, PostOutcome.engagement_score)
        .select_from(PostOutcome)
        .join(Post, Post.id == PostOutcome.post_id)
        .where(Post.posted_at.isnot(None), Post.posted_at >= cutoff, PostOutcome.engagement_score.isnot(None))
    ).all()
    by_bucket: dict[str, list[float]] = defaultdict(list)
    for posted_at, score in rows:
        pat_ist = to_ist(_aware_utc(posted_at))
        by_bucket[hour_bucket(pat_ist.hour)].append(score)
    qualified = {k: statistics.fmean(v) for k, v in by_bucket.items() if len(v) >= min_samples}
    if not qualified:
        return None
    return max(qualified, key=lambda k: qualified[k])


def _products_by_url_map(s: Session) -> dict[str, MerchantProduct]:
    """Best-effort URL -> ``MerchantProduct`` correlation -- no FK exists
    between ``EnrichedDeal`` and ``MerchantProduct``, so this matches by URL
    string, the same approach ``generation/revalidate.py`` uses per-deal. When
    more than one product happens to share a URL, the most recently verified
    one wins."""
    out: dict[str, MerchantProduct] = {}
    for p in s.scalars(select(MerchantProduct).where(MerchantProduct.product_url.isnot(None))):
        cur = out.get(p.product_url)
        if cur is None:
            out[p.product_url] = p
            continue
        cur_v, p_v = _aware_utc(cur.last_verified_at), _aware_utc(p.last_verified_at)
        if p_v is not None and (cur_v is None or p_v > cur_v):
            out[p.product_url] = p
    return out


def _build_context(s: Session, now: datetime | None = None) -> _ScoringContext:
    return _ScoringContext(
        now=now or datetime.now(timezone.utc),
        affinity=_merchant_affinity_map(s),
        coverage=_competitor_coverage_map(s),
        best_bucket=_best_hour_bucket(s),
        products_by_url=_products_by_url_map(s),
    )


class DealScoringEngine:
    """Stateless scorer -- every method takes its own ``Session``; nothing is
    cached across calls (mirrors ``score_all_active(s)`` usage in
    upgrade.md's report checklist: ``DealScoringEngine().score_all_active(s)``)."""

    def score_deal(self, s: Session, deal: EnrichedDeal, *, now: datetime | None = None) -> tuple[float, dict]:
        """Score a single deal. Builds its own one-off context (fine for
        ad-hoc/test use; ``score_all_active`` builds the context once and
        reuses it across every deal in the run for efficiency)."""
        ctx = _build_context(s, now)
        return self._score(deal, ctx)

    def score_all_active(self, s: Session) -> int:
        """Scores every deal with ``deal_validity != 'invalid'``, inserting
        one ``DealScore`` history row per deal for this run. Returns the
        count scored."""
        ctx = _build_context(s)
        deals = s.scalars(
            select(EnrichedDeal).where(EnrichedDeal.deal_validity != DealValidity.INVALID)
        ).all()
        n = 0
        for deal in deals:
            score, components = self._score(deal, ctx)
            s.add(DealScore(deal_id=deal.id, score=score, components=components, scored_at=ctx.now))
            n += 1
        s.flush()
        return n

    def _score(self, deal: EnrichedDeal, ctx: _ScoringContext) -> tuple[float, dict]:
        url = deal.clean_url or deal.url
        product = ctx.products_by_url.get(url) if url else None
        now_ist_hour = to_ist(ctx.now).hour
        components = {
            "discount_depth": discount_depth(deal, product),
            "audience_affinity": (
                ctx.affinity.get(deal.merchant_key, UNKNOWN_AFFINITY) if deal.merchant_key else UNKNOWN_AFFINITY
            ),
            "freshness": freshness(deal, now=ctx.now),
            "time_fit": time_fit(ctx.best_bucket, now_ist_hour=now_ist_hour),
            "price_credibility": price_credibility(deal, product, now=ctx.now),
            "scarcity_of_coverage": scarcity_of_coverage(deal.merchant_key, ctx.coverage),
        }
        score = round(100.0 * sum(WEIGHTS[k] * components[k] for k in WEIGHTS), 3)
        return score, components
