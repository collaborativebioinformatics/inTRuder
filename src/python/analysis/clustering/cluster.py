"""Partitioning an embedding view, and scoring how novel each window is.

Three algorithms, chosen because they disagree in useful ways:

``kmeans``
    fast, always returns exactly ``k`` groups, assumes they are round and
    similarly sized. The baseline: if k-means and HDBSCAN agree, the structure
    is not an artefact of either.
``hdbscan``
    density-based, picks its own cluster count, and -- the reason it is the
    default here -- *labels points as noise* (``-1``) instead of forcing every
    window into a group. With 69 samples at some loci and one at others, a
    method that must assign everything will manufacture groups out of the
    singletons.
``agglomerative``
    hierarchical, and the only one that takes a precomputed distance and a
    ``distance_threshold`` instead of a cluster count. Use it when the question
    is "what merges with what", not "what are the k groups".

Scoring
-------
Internal indices (silhouette, Calinski-Harabasz, Davies-Bouldin) say how *tidy*
a partition is, not whether it is real; in 8192 dimensions they are all
optimistic. :func:`agreement` is the one that earns its place: it scores the
partition against the covariates that are already known to structure this data,
and a high score there is a warning, not a success.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

import numpy as np
import pandas as pd

METHODS = ("hdbscan", "kmeans", "agglomerative")

#: Design columns :func:`agreement` scores a partition against by default.
KNOWN_LABELS = ("locus", "sample", "chrom", "cropped")


class Clustering(NamedTuple):
    """Labels plus the settings and the internal scores."""

    labels: np.ndarray
    method: str
    params: dict[str, object]
    scores: dict[str, float]

    @property
    def n_clusters(self) -> int:
        """Excluding the noise label, which is not a cluster."""
        return len(set(self.labels) - {-1})

    @property
    def n_noise(self) -> int:
        return int((self.labels == -1).sum())


def cluster(X: np.ndarray, method: str = "hdbscan", **kwargs) -> Clustering:
    """Dispatch to one of :data:`METHODS` and score the result."""
    if method == "kmeans":
        labels, params = _kmeans(X, **kwargs)
    elif method == "hdbscan":
        labels, params = _hdbscan(X, **kwargs)
    elif method == "agglomerative":
        labels, params = _agglomerative(X, **kwargs)
    else:
        raise ValueError(f"method must be one of {METHODS}, got {method!r}")
    return Clustering(labels, method, params, internal_scores(X, labels, params))


def _kmeans(X, k: int = 8, seed: int = 0, **_) -> tuple[np.ndarray, dict]:
    from sklearn.cluster import KMeans

    k = max(2, min(k, len(X)))
    model = KMeans(n_clusters=k, random_state=seed, n_init=10)
    return model.fit_predict(X), {"k": k, "seed": seed, "metric": "euclidean"}


def _hdbscan(
    X, min_cluster_size: int = 5, min_samples: int | None = None,
    metric: str = "euclidean", **_,
) -> tuple[np.ndarray, dict]:
    from sklearn.cluster import HDBSCAN

    # sklearn's HDBSCAN has no cosine metric; on l2-normalised rows Euclidean
    # is a monotone function of cosine, so `matrix.prepare(..., "l2")` is how
    # you get cosine behaviour here rather than a metric argument.
    min_cluster_size = max(2, min(min_cluster_size, len(X)))
    model = HDBSCAN(
        min_cluster_size=min_cluster_size, min_samples=min_samples, metric=metric
    )
    return model.fit_predict(X), {
        "min_cluster_size": min_cluster_size,
        "min_samples": min_samples,
        "metric": metric,
    }


def _agglomerative(
    X, k: int | None = 8, distance_threshold: float | None = None,
    linkage: str = "average", metric: str = "cosine", **_,
) -> tuple[np.ndarray, dict]:
    from sklearn.cluster import AgglomerativeClustering

    if distance_threshold is not None:
        k = None
    elif k is not None:
        k = max(2, min(k, len(X)))
    model = AgglomerativeClustering(
        n_clusters=k, distance_threshold=distance_threshold,
        linkage=linkage, metric=metric,
    )
    return model.fit_predict(X), {
        "k": k, "distance_threshold": distance_threshold,
        "linkage": linkage, "metric": metric,
    }


def internal_scores(X: np.ndarray, labels: np.ndarray, params: dict) -> dict[str, float]:
    """Silhouette, Calinski-Harabasz and Davies-Bouldin, noise excluded.

    Noise points are dropped first: silhouette treats ``-1`` as a cluster
    otherwise, and a scattered "cluster" of everything HDBSCAN refused drags the
    score down for a reason that has nothing to do with the partition.
    """
    from sklearn.metrics import (
        calinski_harabasz_score,
        davies_bouldin_score,
        silhouette_score,
    )

    keep = labels != -1
    y, Xk = labels[keep], X[keep]
    if len(set(y)) < 2 or len(y) < 3:
        return {"silhouette": float("nan"), "calinski_harabasz": float("nan"),
                "davies_bouldin": float("nan"), "n_scored": len(y)}
    metric = "euclidean" if params.get("metric") in (None, "euclidean") else params["metric"]
    return {
        "silhouette": float(silhouette_score(Xk, y, metric=metric)),
        "calinski_harabasz": float(calinski_harabasz_score(Xk, y)),
        "davies_bouldin": float(davies_bouldin_score(Xk, y)),
        "n_scored": len(y),
    }


def sweep_k(
    X: np.ndarray,
    ks: Sequence[int] = (2, 3, 4, 5, 6, 8, 10, 12, 16, 20),
    method: str = "kmeans",
    design: pd.DataFrame | None = None,
    **kwargs,
) -> pd.DataFrame:
    """Score a range of cluster counts, one row per ``k``.

    Silhouette peaks where the partition is tidiest, which is not necessarily
    where it is most meaningful -- so when ``design`` is given the agreement with
    ``locus`` is reported alongside, and a peak that coincides with the locus
    count is a peak to distrust.
    """
    rows = []
    for k in ks:
        if k >= len(X):
            continue
        result = cluster(X, method=method, k=k, **kwargs)
        row = {"k": k, "method": method, "n_clusters": result.n_clusters,
               "n_noise": result.n_noise, **result.scores}
        if design is not None:
            match = agreement(result.labels, design, ("locus",))
            if not match.empty:
                row["ari_locus"] = float(match.loc[0, "ari"])
        rows.append(row)
    return pd.DataFrame(rows)


def agreement(
    labels: np.ndarray,
    design: pd.DataFrame,
    columns: Sequence[str] = KNOWN_LABELS,
) -> pd.DataFrame:
    """How much of the partition is explained by something we already knew.

    ``ari``
        adjusted Rand index: agreement corrected for chance, so 0 is "no better
        than random" and 1 is identical. Symmetric.
    ``ami``
        adjusted mutual information. Also chance-corrected, but less punished by
        a partition that splits each known group into several -- which is what
        happens when clusters are finer than loci.
    ``homogeneity``
        do clusters contain only one value of the covariate. Directional, and
        the one that catches "every cluster is a single locus" cleanly.
    ``completeness``
        is each value of the covariate confined to one cluster.
    """
    from sklearn.metrics import (
        adjusted_mutual_info_score,
        adjusted_rand_score,
        completeness_score,
        homogeneity_score,
    )

    keep = labels != -1
    y = labels[keep]
    rows = []
    for name in columns:
        if name not in design:
            continue
        truth = design[name].astype(str).to_numpy()[keep]
        if len(set(truth)) < 2 or len(set(y)) < 2:
            continue
        rows.append({
            "covariate": name,
            "n_groups": len(set(truth)),
            "ari": float(adjusted_rand_score(truth, y)),
            "ami": float(adjusted_mutual_info_score(truth, y)),
            "homogeneity": float(homogeneity_score(truth, y)),
            "completeness": float(completeness_score(truth, y)),
            "n_scored": int(keep.sum()),
        })
    return pd.DataFrame(rows)


def novelty_scores(
    X: np.ndarray,
    background: np.ndarray | None = None,
    k: int = 5,
    metric: str = "euclidean",
) -> pd.DataFrame:
    """How far each window sits from what the model expects.

    With ``background`` -- the reference-allele vectors from ``evo-embed
    --background`` -- the score is the distance to the *k*-th nearest background
    window. That is the measurement the project is actually after: the reference
    genome supplies the null, and an insertion whose junction lands far outside
    it is one the reference does not explain.

    Without a background it falls back to Local Outlier Factor within the run
    itself, which finds windows unusual *relative to the other insertions*. That
    is a weaker claim -- the comparison set is no longer the reference -- but it
    needs no second GPU run.

    Both columns are returned as ``score`` with a ``basis`` column naming which
    was used, so downstream code does not have to guess.
    """
    if background is not None and len(background):
        from sklearn.neighbors import NearestNeighbors

        k = max(1, min(k, len(background)))
        nn = NearestNeighbors(n_neighbors=k, metric=metric).fit(background)
        distances, _ = nn.kneighbors(X)
        score = distances[:, -1]
        basis = "background_knn"
    else:
        from sklearn.neighbors import LocalOutlierFactor

        k = max(1, min(20, len(X) - 1))
        lof = LocalOutlierFactor(n_neighbors=k, metric=metric)
        lof.fit_predict(X)
        # negative_outlier_factor_ is ~-1 for inliers and more negative for
        # outliers; flip it so larger always means more unusual, as above.
        score = -lof.negative_outlier_factor_
        basis = "lof"
    return pd.DataFrame({
        "score": np.asarray(score, dtype=float),
        "basis": basis,
        "k": k,
        "rank": pd.Series(score).rank(ascending=False, method="min").astype(int),
    })
