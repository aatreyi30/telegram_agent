"""Post Classifier (Phase 3).

Fits post-type clusters on the whole normalized dataset, assigns each post to a
cluster with a confidence, and derives each cluster's descriptor from its own
feature signature. Re-fitting replaces the current classification version.

Learned, not hardcoded: the ONLY inputs are Phase-2 data-derived features. The
descriptor phrases describe measured feature deviations (e.g. "coupon-heavy"
means this cluster's coupon rate is far above the dataset mean) — they are not
keyword matches against post text.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.services.classification import features as F
from src.services.classification.kmeans import kmeans
from src.services.collection.base import BaseCollector, CollectorResult
from src.db.models import CompetitorPost, Post
from src.db.models_classification import (
    CLASSIFICATION_VERSION,
    PostClassification,
    PostTypeCluster,
)
from src.db.models_normalization import (
    ExtractedPrice,
    NormalizedPost,
    SourceType,
)
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus
from src.logger import get_logger

logger = get_logger(__name__)

# Readable phrase for a feature being notably HIGH / LOW vs the dataset mean.
# This labels a *measured feature*, not a post-text category (RULE 3 safe).
_HIGH_PHRASE = {
    "num_links": "many-links",
    "num_prices": "many-prices",
    "has_coupon": "coupon-heavy",
    "is_multi_deal": "multi-deal",
    "has_threshold": "price-capped",
    "price_max_log": "high-price",
    "price_spread_log": "wide-price-range",
    "emoji_count": "emoji-rich",
    "text_len_log": "long-text",
    "has_cta": "cta-present",
    "merchant_known": "known-merchant",
}
_LOW_PHRASE = {
    "num_links": "few-links",
    "has_coupon": "no-coupon",
    "is_multi_deal": "single-item",
    "price_max_log": "low-price",
    "text_len_log": "short-text",
    "merchant_known": "unresolved-merchant",
}


class PostClassifier(BaseCollector):
    name = "classifier"
    retryable = False

    def __init__(self, k: int = 6, seed: int = 42):
        self.k = k
        self.seed = seed
        self.bus = get_event_bus()

    def run(self, job) -> CollectorResult:
        result = CollectorResult()
        with session_scope() as s:
            post_ids, vectors = self._load_features(s)
        result.processed = len(post_ids)
        if len(post_ids) < self.k:
            result.skipped_reason = (
                f"Not enough normalized posts ({len(post_ids)}) to fit {self.k} clusters. "
                "Run `tgagent normalize` first / lower --k."
            )
            return result

        std_rows, means, stds = F.standardize(vectors)
        km = kmeans(std_rows, self.k, seed=self.seed)

        # cluster stats + raw feature means (data-derived descriptor)
        cluster_meta = self._summarize_clusters(km.labels, vectors, km.centroids)

        added, updated = self._persist(post_ids, km, cluster_meta, means, stds)
        result.added = added
        result.updated = updated
        self.bus.publish(
            Event(
                event_type=EventType.CLUSTERS_UPDATED,
                entity_type="classification",
                entity_id=str(CLASSIFICATION_VERSION),
                data={"k": self.k, "posts": len(post_ids), "inertia": round(km.inertia, 2)},
                job_id=job.id,
            )
        )
        logger.info("[classifier] fit k=%d over %d posts (inertia=%.1f)",
                    self.k, len(post_ids), km.inertia)
        return result

    # ------------------------------------------------------------------ #
    def _load_features(self, s: Session):
        # price values per normalized post
        price_rows = s.execute(
            select(ExtractedPrice.normalized_post_id, ExtractedPrice.amount)
        ).all()
        prices_by_post: dict[int, list[float]] = {}
        for pid, amt in price_rows:
            prices_by_post.setdefault(pid, []).append(amt)

        # raw text lengths, per source table (join by source_id)
        owned_len = dict(
            s.execute(select(Post.id, func.length(Post.text))).all()
        )
        comp_len = dict(
            s.execute(select(CompetitorPost.id, func.length(CompetitorPost.text))).all()
        )

        post_ids: list[int] = []
        vectors: list[list[float]] = []
        for np in s.scalars(select(NormalizedPost).order_by(NormalizedPost.id)):
            if np.source_type == SourceType.OWNED:
                text_len = owned_len.get(np.source_id) or 0
            else:
                text_len = comp_len.get(np.source_id) or 0
            vec = F.build_vector(
                num_links=np.num_links,
                num_prices=np.num_prices,
                has_coupon=np.has_coupon,
                is_multi_deal=np.is_multi_deal,
                price_threshold=np.price_threshold,
                price_values=prices_by_post.get(np.id, []),
                emoji_count=len(np.emojis or []),
                text_len=text_len,
                has_cta=bool(np.cta_texts),
                merchant_known=np.primary_merchant_key is not None,
            )
            post_ids.append(np.id)
            vectors.append(vec)
        return post_ids, vectors

    def _summarize_clusters(self, labels, vectors, centroids):
        k = len(centroids)
        dim = len(F.FEATURE_NAMES)
        sums = [[0.0] * dim for _ in range(k)]
        counts = [0] * k
        for lab, v in zip(labels, vectors):
            counts[lab] += 1
            for j in range(dim):
                sums[lab][j] += v[j]
        raw_means = [
            [sums[c][j] / counts[c] if counts[c] else 0.0 for j in range(dim)]
            for c in range(k)
        ]
        meta = []
        for c in range(k):
            descriptor = self._describe(centroids[c])
            fm = {F.FEATURE_NAMES[j]: round(raw_means[c][j], 3) for j in range(dim)}
            meta.append({"size": counts[c], "descriptor": descriptor, "feature_means": fm})
        return meta

    @staticmethod
    def _describe(std_centroid: list[float]) -> str:
        """Descriptor from standardized centroid deviations (data-derived)."""
        parts: list[tuple[float, str]] = []
        for j, name in enumerate(F.FEATURE_NAMES):
            z = std_centroid[j]
            if z >= 0.6 and name in _HIGH_PHRASE:
                parts.append((abs(z), _HIGH_PHRASE[name]))
            elif z <= -0.6 and name in _LOW_PHRASE:
                parts.append((abs(z), _LOW_PHRASE[name]))
        parts.sort(reverse=True)
        phrases = [p for _, p in parts[:4]]
        return " · ".join(phrases) if phrases else "baseline (near dataset average)"

    def _persist(self, post_ids, km, cluster_meta, means, stds) -> tuple[int, int]:
        now = datetime.now(timezone.utc)
        with session_scope() as s:
            # replace prior fit for this version
            s.query(PostClassification).filter(
                PostClassification.classification_version == CLASSIFICATION_VERSION
            ).delete()
            s.query(PostTypeCluster).filter(
                PostTypeCluster.classification_version == CLASSIFICATION_VERSION
            ).delete()
            s.flush()

            cluster_row_ids: list[int] = []
            for ci in range(len(km.centroids)):
                centroid = {F.FEATURE_NAMES[j]: round(km.centroids[ci][j], 4)
                            for j in range(len(F.FEATURE_NAMES))}
                row = PostTypeCluster(
                    classification_version=CLASSIFICATION_VERSION,
                    cluster_index=ci,
                    size=cluster_meta[ci]["size"],
                    centroid=centroid,
                    feature_means=cluster_meta[ci]["feature_means"],
                    descriptor=cluster_meta[ci]["descriptor"],
                    fitted_at=now,
                )
                s.add(row)
                s.flush()
                cluster_row_ids.append(row.id)

            added = 0
            for pid, lab, (nearest, second) in zip(post_ids, km.labels, km.distances):
                conf = 1.0 - (nearest / second) if second > 0 else 1.0
                conf = max(0.0, min(1.0, round(conf, 3)))
                s.add(PostClassification(
                    normalized_post_id=pid,
                    cluster_id=cluster_row_ids[lab],
                    classification_version=CLASSIFICATION_VERSION,
                    confidence=conf,
                    classified_at=now,
                ))
                added += 1
        return added, 0
