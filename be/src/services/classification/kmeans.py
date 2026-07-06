"""Pure-Python k-means (dependency-free; deterministic with a fixed seed).

Deterministic k-means++ seeding + Lloyd iterations. No numpy/sklearn so it
installs on any interpreter (avoids the Python 3.14 compiled-wheel problem).
Adequate for the modest feature dimensionality and dataset sizes here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


def _sq_dist(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b))


@dataclass
class KMeansResult:
    centroids: list[list[float]]
    labels: list[int]
    # per-point (nearest_dist, second_nearest_dist) for confidence scoring
    distances: list[tuple[float, float]]
    inertia: float


def _kpp_init(data: list[list[float]], k: int, rng: random.Random) -> list[list[float]]:
    centroids = [list(data[rng.randrange(len(data))])]
    while len(centroids) < k:
        d2 = []
        for p in data:
            d2.append(min(_sq_dist(p, c) for c in centroids))
        total = sum(d2) or 1.0
        # deterministic weighted pick using rng
        target = rng.random() * total
        acc = 0.0
        chosen = len(data) - 1
        for i, val in enumerate(d2):
            acc += val
            if acc >= target:
                chosen = i
                break
        centroids.append(list(data[chosen]))
    return centroids


def kmeans(
    data: list[list[float]],
    k: int,
    *,
    seed: int = 42,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> KMeansResult:
    if not data:
        return KMeansResult([], [], [], 0.0)
    k = max(1, min(k, len(data)))
    dim = len(data[0])
    rng = random.Random(seed)
    centroids = _kpp_init(data, k, rng)

    labels = [0] * len(data)
    for _ in range(max_iter):
        # assignment
        changed = False
        for i, p in enumerate(data):
            best, best_d = 0, float("inf")
            for ci, c in enumerate(centroids):
                d = _sq_dist(p, c)
                if d < best_d:
                    best_d, best = d, ci
            if labels[i] != best:
                labels[i] = best
                changed = True
        # update
        sums = [[0.0] * dim for _ in range(k)]
        counts = [0] * k
        for i, p in enumerate(data):
            counts[labels[i]] += 1
            row = sums[labels[i]]
            for j in range(dim):
                row[j] += p[j]
        shift = 0.0
        for ci in range(k):
            if counts[ci] == 0:
                continue  # keep empty centroid as-is (deterministic)
            new_c = [sums[ci][j] / counts[ci] for j in range(dim)]
            shift += _sq_dist(new_c, centroids[ci])
            centroids[ci] = new_c
        if not changed or shift < tol:
            break

    # final distances (nearest + second nearest) + inertia
    distances: list[tuple[float, float]] = []
    inertia = 0.0
    for p in data:
        ds = sorted(_sq_dist(p, c) for c in centroids)
        nearest = ds[0]
        second = ds[1] if len(ds) > 1 else ds[0]
        distances.append((nearest ** 0.5, second ** 0.5))
        inertia += nearest
    return KMeansResult(centroids, labels, distances, inertia)
