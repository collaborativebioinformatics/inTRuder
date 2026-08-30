"""PCA, UMAP and t-SNE over one embedding view.

All three go through :func:`reduce` and come back as a :class:`Reduction`, which
carries the coordinates *and* the settings that produced them. That pairing is
the point: a UMAP scatter is uninterpretable without ``n_neighbors`` and the
metric, and those are exactly what gets lost when coordinates are passed around
as a bare array.

The PCA pre-step
----------------
UMAP and t-SNE both build a k-nearest-neighbour graph first, and both are
noticeably faster and no less faithful when that graph is built in ~50 PCA
dimensions rather than 8192. It is the standard pipeline in single-cell analysis
for the same reason it applies here: at 8192 dimensions and a few thousand
points, most of the coordinate space is noise, and the neighbour graph is what
the whole method rests on.

``pca_init=0`` turns it off, for when you want the neighbour graph in the
original space and can afford it.

Metric
------
``cosine`` is the default for UMAP because Evo 2 vectors carry a magnitude that
tracks how much sequence was pooled, not what was in it. Combined with
``matrix.prepare(..., "l2")`` the choice is redundant but harmless -- on unit
vectors, Euclidean and cosine neighbourhoods coincide.

Reproducibility
---------------
Every method takes ``seed``. UMAP is stochastic and its layout changes
qualitatively between runs; an unseeded UMAP in a figure is not reproducible,
and with ``n_jobs > 1`` umap-learn is not exactly reproducible even seeded, so
this module pins ``n_jobs=1`` whenever a seed is given.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np

METHODS = ("pca", "umap", "tsne")


class Reduction(NamedTuple):
    """Coordinates plus everything needed to interpret or redo them."""

    coords: np.ndarray
    method: str
    params: dict[str, object]

    explained_variance_ratio: np.ndarray | None = None
    """PCA only: variance kept per component. ``None`` elsewhere -- UMAP and
    t-SNE have no such quantity, and inventing one would invite reading their
    axes as if they were scaled."""

    def frame(self):
        """Coordinates as a DataFrame with ``comp1``..``compN`` columns."""
        import pandas as pd

        return pd.DataFrame(
            self.coords,
            columns=[f"comp{i + 1}" for i in range(self.coords.shape[1])],
        )


def pca(X: np.ndarray, n_components: int = 2, seed: int = 0) -> Reduction:
    """Linear reduction, with the variance it kept."""
    from sklearn.decomposition import PCA

    n_components = min(n_components, *X.shape)
    model = PCA(n_components=n_components, random_state=seed)
    coords = model.fit_transform(X)
    return Reduction(
        coords=coords,
        method="pca",
        params={"n_components": n_components, "seed": seed},
        explained_variance_ratio=model.explained_variance_ratio_,
    )


def umap_embed(
    X: np.ndarray,
    n_components: int = 2,
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    metric: str = "cosine",
    pca_init: int = 50,
    seed: int = 0,
) -> Reduction:
    """UMAP, optionally on PCA coordinates.

    ``n_neighbors`` is the one setting worth sweeping. It sets the scale at
    which structure is preserved: low values (5-15) resolve local neighbourhoods
    and fragment, high values (50+) keep the global arrangement and merge. On
    this data the natural check is whether a value exists at which samples
    separate *without* the loci separating -- if every setting recovers the
    locus, the view is a flank view and no parameter will fix that.
    """
    import umap

    X, pre = _pca_init(X, pca_init, seed)
    n_neighbors = max(2, min(n_neighbors, len(X) - 1))
    model = umap.UMAP(
        n_components=n_components,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric=metric,
        random_state=seed,
        n_jobs=1,  # required for `random_state` to actually be deterministic
    )
    return Reduction(
        coords=model.fit_transform(X),
        method="umap",
        params={
            "n_components": n_components, "n_neighbors": n_neighbors,
            "min_dist": min_dist, "metric": metric, "pca_init": pre, "seed": seed,
        },
    )


def tsne(
    X: np.ndarray,
    n_components: int = 2,
    perplexity: float = 30.0,
    metric: str = "cosine",
    pca_init: int = 50,
    seed: int = 0,
) -> Reduction:
    """t-SNE. Preserves local neighbourhoods only -- distances *between*
    clusters in the output carry no meaning at all, which is the single most
    common way these plots get over-read."""
    from sklearn.manifold import TSNE

    X, pre = _pca_init(X, pca_init, seed)
    perplexity = max(2.0, min(perplexity, (len(X) - 1) / 3))
    model = TSNE(
        n_components=n_components,
        perplexity=perplexity,
        metric=metric,
        init="pca" if metric == "euclidean" else "random",
        random_state=seed,
    )
    return Reduction(
        coords=model.fit_transform(X),
        method="tsne",
        params={
            "n_components": n_components, "perplexity": perplexity,
            "metric": metric, "pca_init": pre, "seed": seed,
        },
    )


def reduce(X: np.ndarray, method: str = "umap", **kwargs) -> Reduction:
    """Dispatch to one of :data:`METHODS`."""
    if method == "pca":
        kwargs.pop("metric", None)
        kwargs.pop("pca_init", None)
        kwargs.pop("n_neighbors", None)
        kwargs.pop("min_dist", None)
        kwargs.pop("perplexity", None)
        return pca(X, **kwargs)
    if method == "umap":
        kwargs.pop("perplexity", None)
        return umap_embed(X, **kwargs)
    if method == "tsne":
        kwargs.pop("n_neighbors", None)
        kwargs.pop("min_dist", None)
        return tsne(X, **kwargs)
    raise ValueError(f"method must be one of {METHODS}, got {method!r}")


def _pca_init(X: np.ndarray, n: int, seed: int) -> tuple[np.ndarray, int]:
    """Reduce to ``n`` PCA dimensions first, if that is fewer than we have."""
    if n and n < min(X.shape):
        return pca(X, n_components=n, seed=seed).coords, n
    return X, 0
