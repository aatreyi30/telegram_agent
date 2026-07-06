"""Phase 3 tests — feature building + k-means (deterministic, no DB/network)."""

from __future__ import annotations

from src.services.classification import features as F
from src.services.classification.kmeans import kmeans


def test_feature_vector_shape_and_flags():
    vec = F.build_vector(
        num_links=5, num_prices=2, has_coupon=False, is_multi_deal=True,
        price_threshold=500.0, price_values=[199.0, 499.0], emoji_count=3,
        text_len=120, has_cta=True, merchant_known=False,
    )
    assert len(vec) == len(F.FEATURE_NAMES)
    d = dict(zip(F.FEATURE_NAMES, vec))
    assert d["num_links"] == 5.0
    assert d["is_multi_deal"] == 1.0
    assert d["has_coupon"] == 0.0
    assert d["has_threshold"] == 1.0
    assert d["merchant_known"] == 0.0


def test_standardize_zero_mean_unit_std():
    rows = [F.build_vector(
        num_links=n, num_prices=1, has_coupon=bool(n % 2), is_multi_deal=n > 2,
        price_threshold=None, price_values=[100.0 * n], emoji_count=n,
        text_len=10 * n, has_cta=False, merchant_known=True,
    ) for n in range(1, 11)]
    std, means, stds = F.standardize(rows)
    dim = len(F.FEATURE_NAMES)
    # each standardized column has ~0 mean
    for j in range(dim):
        col_mean = sum(r[j] for r in std) / len(std)
        assert abs(col_mean) < 1e-9
    assert len(means) == dim and len(stds) == dim


def test_kmeans_is_deterministic_and_separates_groups():
    # two clearly separated blobs in 2D
    group_a = [[0.0, 0.0], [0.1, 0.1], [0.0, 0.2], [0.2, 0.0]]
    group_b = [[10.0, 10.0], [10.1, 9.9], [9.8, 10.2], [10.2, 10.0]]
    data = group_a + group_b

    r1 = kmeans(data, k=2, seed=42)
    r2 = kmeans(data, k=2, seed=42)
    assert r1.labels == r2.labels  # deterministic with fixed seed

    # the two groups end up in different clusters
    assert len(set(r1.labels[:4])) == 1
    assert len(set(r1.labels[4:])) == 1
    assert r1.labels[0] != r1.labels[4]


def test_kmeans_handles_k_larger_than_data():
    r = kmeans([[1.0], [2.0]], k=5, seed=1)
    assert len(r.centroids) <= 2  # k clamped to n
