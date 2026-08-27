"""The questions to ask before believing a picture.

A UMAP of 8192-dimensional vectors will always produce islands. The islands are
not the finding; what the islands *track* is the finding, and on this data there
are three things they are likely to track that are not biology:

**Locus.** 69 samples are called at one breakpoint and share their 3,584 bp
flanks, so their windows are near-identical by construction. Clusters that
recover the locus have recovered the input, not a result.

**Insertion length.** It runs 52 bp to 54 kb in this callset (median 118), it
sets how many tokens the ``repeat`` span pools, and it is exactly the sort of
scalar a neural representation encodes linearly. If component 1 correlates with
``log_length`` at rho 0.9, component 1 *is* length.

**Cropping and N content.** ``repeat_crop`` truncates long insertions and
``max_n_fraction`` lets marginal windows through; both put a step change into
the vectors that has no biological meaning.

:func:`confound_report` measures all of them against any set of coordinates, and
:func:`neighbor_purity` asks the same question of the full-dimensional space
before any reduction has had a chance to invent structure.

Nothing here decides anything. It produces numbers next to which a claim can be
made or withdrawn.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

#: Continuous covariates scored by :func:`confound_report`, if present.
CONTINUOUS = ("log_length", "insert_length", "n_fraction", "pos")

#: Categorical covariates scored by :func:`confound_report`, if present.
CATEGORICAL = ("locus", "sample", "chrom", "cropped")


def confound_report(
    coords: np.ndarray,
    design: pd.DataFrame,
    continuous: Sequence[str] = CONTINUOUS,
    categorical: Sequence[str] = CATEGORICAL,
) -> pd.DataFrame:
    """What each coordinate axis tracks.

    One row per (component, covariate). For a continuous covariate the statistic
    is Spearman rho -- rank-based, so a monotone-but-curved relationship still
    shows up, which a Pearson r on a log-scaled length would miss. For a
    categorical one it is eta squared: the fraction of that component's variance
    lying *between* groups rather than within them.

    Two columns carry the categorical answer. ``value`` is the raw eta squared;
    ``adjusted`` is :func:`epsilon_squared`, the same thing with the group-count
    bias taken out, and it is the one to read. They diverge sharply when groups
    are many and small -- on the benchmark run ``sample`` scores eta 0.57 and
    epsilon -0.23, i.e. it explains nothing at all -- so ranking on the raw
    number promotes exactly the covariates that cannot mean anything. Rows are
    ordered by ``abs_value``, which follows ``adjusted`` where it exists.

    Read it as a veto list. A component with ``adjusted = 0.95`` against
    ``locus`` is a locus axis whatever else it correlates with.
    """
    from scipy.stats import spearmanr

    coords = np.asarray(coords, dtype=np.float64)
    if len(coords) != len(design):
        raise ValueError(
            f"{len(coords)} coordinate rows but {len(design)} design rows; "
            "subset the design with the mask that produced the coordinates"
        )

    rows = []
    for j in range(coords.shape[1]):
        axis = coords[:, j]
        for name in continuous:
            if name not in design:
                continue
            values = pd.to_numeric(design[name], errors="coerce").to_numpy(float)
            ok = np.isfinite(values) & np.isfinite(axis)
            if ok.sum() < 3 or np.ptp(values[ok]) == 0:
                continue
            rho = spearmanr(axis[ok], values[ok]).statistic
            rows.append({
                "component": j + 1, "covariate": name, "kind": "continuous",
                "statistic": "spearman_rho", "value": float(rho),
                "adjusted": pd.NA, "abs_value": abs(float(rho)),
                "n_groups": pd.NA,
            })
        for name in categorical:
            if name not in design:
                continue
            groups = design[name].astype(str).to_numpy()
            eta = eta_squared(axis, groups)
            if eta is None:
                continue
            adjusted = epsilon_squared(axis, groups)
            rows.append({
                "component": j + 1, "covariate": name, "kind": "categorical",
                "statistic": "eta_sq", "value": float(eta),
                "adjusted": pd.NA if adjusted is None else float(adjusted),
                # Rank on the unbiased number: a covariate with 65 groups over
                # 100 rows scores ~0.65 on the raw one whatever the data says.
                "abs_value": abs(float(eta if adjusted is None else adjusted)),
                "n_groups": len(set(groups)),
            })
    return pd.DataFrame(rows)


def eta_squared(values: np.ndarray, groups: np.ndarray) -> float | None:
    """Fraction of ``values`` variance explained by group membership.

    ``None`` when the question is empty -- one group, or as many groups as
    points, where the answer is 0 or 1 by arithmetic rather than by data.

    **Biased upward with many groups**, and badly so here: any split into *k*
    groups explains about ``(k-1)/(n-1)`` of the variance of pure noise, which
    for the 65 samples over 100 windows in the benchmark run is 0.65. An eta of
    0.57 against ``sample`` looks like half the variance and is in fact *below*
    chance. Use :func:`epsilon_squared` to read it; this returns the raw
    quantity because that is what the name means.
    """
    values = np.asarray(values, dtype=np.float64)
    keys, codes = np.unique(np.asarray(groups), return_inverse=True)
    if len(keys) < 2 or len(keys) == len(values):
        return None
    total = values.var()
    if total == 0:
        return None
    counts = np.bincount(codes)
    means = np.bincount(codes, weights=values) / counts
    between = float((counts * (means - values.mean()) ** 2).sum() / len(values))
    return between / total


def epsilon_squared(values: np.ndarray, groups: np.ndarray) -> float | None:
    """:func:`eta_squared` with the group-count bias removed.

    ``1 - (1 - eta^2) * (n - 1) / (n - k)``: the same quantity an adjusted R^2
    is to an R^2. Zero means "no better than splitting at random", and it can go
    **negative**, which is the informative case -- it says the grouping explains
    less than a random one of the same shape would.

    This is the number to read when the group counts differ between covariates,
    which they always do here: 31 loci and 65 samples over 100 windows are not
    comparable on the raw scale.
    """
    eta = eta_squared(values, groups)
    if eta is None:
        return None
    n = len(values)
    k = len(np.unique(np.asarray(groups)))
    if n - k <= 0:
        return None
    return 1.0 - (1.0 - eta) * (n - 1) / (n - k)


def neighbor_purity(
    X: np.ndarray,
    design: pd.DataFrame,
    labels: Sequence[str] = ("locus", "sample"),
    k: int = 10,
    metric: str = "cosine",
) -> pd.DataFrame:
    """Of each point's ``k`` nearest neighbours, how many share its label.

    Asked in the *original* space, before reduction, because UMAP is under no
    obligation to preserve this and a purity computed on its output measures
    UMAP as much as the embedding. Reported against a baseline: the purity you
    would get from labels shuffled at random, which for a label with many small
    groups is not zero.

    A junction view with locus purity 0.98 has learned the flanks. A view with
    locus purity near the baseline and *some* other structure is the interesting
    case.
    """
    from sklearn.neighbors import NearestNeighbors

    k = min(k, len(X) - 1)
    if k < 1:
        raise ValueError("need at least two rows to have a neighbour")

    nn = NearestNeighbors(n_neighbors=k + 1, metric=metric).fit(X)
    # Column 0 is the point itself; drop it.
    idx = nn.kneighbors(X, return_distance=False)[:, 1:]

    rows = []
    for name in labels:
        if name not in design:
            continue
        values = design[name].astype(str).to_numpy()
        shared = (values[idx] == values[:, None]).mean()
        counts = pd.Series(values).value_counts().to_numpy(float)
        # Chance level for "a random other point shares my label".
        baseline = float((counts * (counts - 1)).sum() / (len(values) * (len(values) - 1)))
        rows.append({
            "label": name, "k": k, "purity": float(shared),
            "baseline": baseline,
            "excess": float(shared) - baseline,
            "n_groups": len(counts),
        })
    return pd.DataFrame(rows)


def view_grid(
    emb,
    design: pd.DataFrame,
    layers: Sequence[str] | None = None,
    segments: Sequence[str] | None = None,
    strand: str = "both",
    normalize: str = "l2",
    k: int = 10,
    metric: str = "cosine",
) -> pd.DataFrame:
    """Score every (layer, segment) view so the choice is made on evidence.

    A run holds 9 layers x 5 segments = 45 views and there is no principled way
    to pick one a priori -- the block-type reasoning in
    :mod:`evo.embeddings.extract` says which layers *might* carry placement, not
    which does. This runs the cheap diagnostics over all of them and returns a
    table: mean per-dimension variance (is there anything here at all), neighbour
    purity by locus (is it just the flanks) and by sample, and the excess over
    chance for each.

    Layers that overflowed float16 are skipped, not zero-filled.
    """
    from analysis.matrix import finite_layers, prepare, view

    segments = list(segments or emb.segments)
    rows = []
    for segment in segments:
        usable = finite_layers(emb, segment)
        for layer in list(layers or emb.layers):
            if layer not in usable:
                rows.append({
                    "layer": layer, "segment": segment, "status": "nonfinite",
                    "dim_var": np.nan, "locus_purity": np.nan,
                    "locus_excess": np.nan, "sample_excess": np.nan,
                })
                continue
            X = view(emb, layer, segment, strand)
            dim_var = float(X.var(axis=0).mean())
            purity = neighbor_purity(
                prepare(X, normalize), design, ("locus", "sample"), k, metric
            ).set_index("label")
            rows.append({
                "layer": layer, "segment": segment, "status": "ok",
                "dim_var": dim_var,
                "locus_purity": _get(purity, "locus", "purity"),
                "locus_excess": _get(purity, "locus", "excess"),
                "sample_excess": _get(purity, "sample", "excess"),
            })
    return pd.DataFrame(rows)


def _get(frame: pd.DataFrame, label: str, column: str) -> float:
    if label not in frame.index:
        return float("nan")
    return float(frame.loc[label, column])
