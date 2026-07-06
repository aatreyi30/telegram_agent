"""Feature extraction for classification.

All features are DATA-DERIVED from Phase-2 normalized entities — no keyword
lists, no hardcoded categories. Each normalized post becomes a numeric vector;
the classifier standardizes these across the dataset before clustering.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Ordered, stable feature names (order matters for vector<->dict mapping).
FEATURE_NAMES: list[str] = [
    "num_links",
    "num_prices",
    "has_coupon",
    "is_multi_deal",
    "has_threshold",
    "price_min_log",     # log1p of min extracted price (0 if none)
    "price_max_log",     # log1p of max extracted price (0 if none)
    "price_spread_log",  # log1p of (max-min) price
    "emoji_count",
    "text_len_log",      # log1p of text length
    "has_cta",
    "merchant_known",
]


@dataclass
class PostFeatureRow:
    normalized_post_id: int
    vector: list[float]


def build_vector(
    *,
    num_links: int,
    num_prices: int,
    has_coupon: bool,
    is_multi_deal: bool,
    price_threshold: float | None,
    price_values: list[float],
    emoji_count: int,
    text_len: int,
    has_cta: bool,
    merchant_known: bool,
) -> list[float]:
    pmin = min(price_values) if price_values else 0.0
    pmax = max(price_values) if price_values else 0.0
    spread = (pmax - pmin) if price_values else 0.0
    return [
        float(num_links),
        float(num_prices),
        1.0 if has_coupon else 0.0,
        1.0 if is_multi_deal else 0.0,
        1.0 if price_threshold is not None else 0.0,
        math.log1p(pmin),
        math.log1p(pmax),
        math.log1p(spread),
        float(emoji_count),
        math.log1p(max(text_len, 0)),
        1.0 if has_cta else 0.0,
        1.0 if merchant_known else 0.0,
    ]


def standardize(rows: list[list[float]]) -> tuple[list[list[float]], list[float], list[float]]:
    """Z-score standardize columns. Returns (standardized_rows, means, stds).

    Means/stds are data-derived and stored so future posts map consistently.
    """
    n = len(rows)
    dim = len(FEATURE_NAMES)
    if n == 0:
        return [], [0.0] * dim, [1.0] * dim
    means = [0.0] * dim
    for r in rows:
        for j in range(dim):
            means[j] += r[j]
    means = [m / n for m in means]
    stds = [0.0] * dim
    for r in rows:
        for j in range(dim):
            stds[j] += (r[j] - means[j]) ** 2
    stds = [math.sqrt(s / n) or 1.0 for s in stds]  # avoid div-by-zero
    out = [[(r[j] - means[j]) / stds[j] for j in range(dim)] for r in rows]
    return out, means, stds


def apply_standardize(vector: list[float], means: list[float], stds: list[float]) -> list[float]:
    return [(vector[j] - means[j]) / (stds[j] or 1.0) for j in range(len(vector))]
