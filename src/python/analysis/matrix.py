"""From a stored embedding run to the matrix an estimator can take.

Every downstream question -- reduce it, cluster it, score it -- starts from one
``(n_windows, d)`` float32 array. Getting there involves four decisions that are
easy to make silently and expensive to make wrong, so they all live here:

**Which view.** A run stores ``(n_windows, n_layers, n_segments, 2 * d_model)``.
Layers and segments are not features to be concatenated -- they are alternative
*views* of the same window, and mixing them just averages a well-behaved one
with a badly-scaled one. :func:`view` takes exactly one.

**Which strand half.** Each vector is ``concat(forward, reverse_complement)``.
The two halves are different views, not duplicates (mean cosine between them:
0.31 on ``benchA.npz``), and under ``last`` pooling they read opposite ends of
the span. :func:`view` can return either half alone.

**Whether the numbers are usable.** ``store.save`` casts to float16, and on the
first real run ``blocks.30`` and ``blocks.31`` came back ~100% ``+/-inf``
because their activations exceed float16's 65504 range. Silently propagating
that gives an all-NaN UMAP with no error anywhere. :func:`view` refuses, and
:func:`finite_layers` tells you what is left.

**What "distance" means.** Raw Evo 2 vectors have per-layer scales that differ
by orders of magnitude, so Euclidean distance on them is dominated by whichever
dimensions happen to be large. :func:`prepare` offers the three defensible
choices and makes you name one.

The confound this module exists to let you remove
------------------------------------------------

At one locus every sample shares the same flanks, so most of a window is
identical between samples by construction. Measured at ``chr1:90258`` over its
39 called samples, ``blocks.26``:

===============  ==================  ==================
segment          max deviation, fwd  max deviation, rev
===============  ==================  ==================
``left``                      0.011               0.024
``junction_5p``               6.015               1.715
``junction_3p``               1.255               6.456
``right``                     0.035               0.009
===============  ==================  ==================

The flanks are constant to within numerical noise -- Evo 2 is autoregressive, so
forward-strand flank tokens cannot see the insertion at all, and what deviation
there is comes from the length-dependent FFT used by the long convolutions.
Cluster raw flank vectors and you recover the locus, which you already knew.

Two ways out, both here:

* pick a junction segment, where the 500x larger spread lives; and
* subtract the **reference allele** at the same breakpoint (:func:`delta`),
  which cancels the locus baseline and leaves what the insertion did.

``delta`` is the reason ``evo-embed --background`` exists. Without it the
reference genome is only implicit in the flanks, and there is nothing to
subtract.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from evo.embeddings.store import Embeddings, load

#: Normalisations offered by :func:`prepare`, and what each is for.
NORMALIZATIONS = ("none", "center", "l2", "zscore")

#: Metadata columns :func:`design` always produces, in output order.
DESIGN_COLUMNS = (
    "row", "chrom", "pos", "locus", "sample", "svid",
    "insert_length", "log_length", "n_fraction", "cropped",
)


def load_runs(paths: Sequence[str]) -> Embeddings:
    """Concatenate the shards of one sharded run into a single :class:`Embeddings`.

    ``evo-embed --offset`` exists because a full callset is ~16 h on one L4 and
    an ephemeral worker can lose the whole thing, so the normal shape of a
    finished run is *several* ``.npz`` files, not one. Rows concatenate in the
    order given; layers, segments and the window-construction settings must
    agree, because a shard cut with a different ``--flank`` is not the same
    experiment and averaging the two would not say so.
    """
    if not paths:
        raise ValueError("no embedding files given")

    runs = [load(p) for p in paths]
    first = runs[0]
    for path, run in zip(paths[1:], runs[1:]):
        if run.layers != first.layers:
            raise ValueError(f"{path}: layers {run.layers} != {first.layers}")
        if run.segments != first.segments:
            raise ValueError(f"{path}: segments {run.segments} != {first.segments}")
        for key in ("model", "flank", "junction", "repeat_crop", "pooling"):
            a, b = first.attrs.get(key), run.attrs.get(key)
            if a != b:
                raise ValueError(f"{path}: {key}={b!r} but first shard has {a!r}")
    if len(runs) == 1:
        return first

    meta_keys = set(first.meta) & set.intersection(*(set(r.meta) for r in runs))
    attrs = dict(first.attrs)
    attrs["shards"] = str(len(runs))
    attrs.pop("offset", None)
    attrs.pop("limit", None)
    return Embeddings(
        vectors=np.concatenate([r.vectors for r in runs]),
        layers=first.layers,
        segments=first.segments,
        meta={k: np.concatenate([r.meta[k] for r in runs]) for k in meta_keys},
        attrs=attrs,
    )


def finite_layers(emb: Embeddings, segment: str | None = None) -> list[str]:
    """The layers whose stored values are all finite.

    Checked rather than assumed: this is the guard against the float16 overflow
    that made ``blocks.30``/``blocks.31`` unusable in the first run. Restricting
    to one ``segment`` asks the narrower question, since a layer can overflow on
    the high-variance junction spans while its flanks stay in range.
    """
    if segment is None:
        block = emb.vectors
    else:
        si = _index(emb.segments, segment, "segment")
        block = emb.vectors[:, :, si, :]
    # One layer at a time: float16 -> float32 on the whole array would triple a
    # multi-gigabyte run in memory just to answer a yes/no question per layer.
    return [
        name
        for li, name in enumerate(emb.layers)
        if np.isfinite(block[:, li].astype(np.float32)).all()
    ]


def view(
    emb: Embeddings,
    layer: str,
    segment: str,
    strand: str = "both",
    allow_nonfinite: bool = False,
) -> np.ndarray:
    """The ``(n_windows, d)`` float32 matrix for one layer, segment and strand.

    ``strand`` is ``"forward"``, ``"reverse"`` or ``"both"``. Forward-strand
    vectors summarise everything *upstream* of the span; reverse-strand ones
    everything downstream. For a junction under ``last`` pooling that is the
    difference between "what does the model make of arriving at this
    breakpoint" and "...of leaving it", and they are worth looking at apart.

    Non-finite values raise rather than propagate. ``allow_nonfinite`` replaces
    them with zeros instead, which is a deliberate choice to analyse a damaged
    layer, not a default.
    """
    X = emb.view(layer, segment).astype(np.float32)

    half = X.shape[1] // 2
    if strand == "forward":
        X = X[:, :half]
    elif strand == "reverse":
        X = X[:, half:]
    elif strand != "both":
        raise ValueError(f"strand must be forward, reverse or both, got {strand!r}")

    bad = ~np.isfinite(X)
    if bad.any():
        if not allow_nonfinite:
            raise ValueError(
                f"{layer}/{segment}: {bad.mean():.1%} of values are inf or NaN. "
                "float16 storage overflows on the deepest blocks; usable layers "
                f"here are {finite_layers(emb, segment)}. Pass "
                "allow_nonfinite=True to zero them instead."
            )
        X = np.where(bad, 0.0, X)
    return np.ascontiguousarray(X)


def prepare(X: np.ndarray, normalize: str = "l2") -> np.ndarray:
    """Put a view on a scale where a distance means something.

    ``none``
        raw. Only sensible when you have already checked the scale.
    ``center``
        subtract the column mean. Removes the constant part of a view -- which
        for a flank segment is nearly all of it -- and leaves Euclidean
        distance intact otherwise. What PCA does internally anyway.
    ``l2``
        scale each row to unit norm, so Euclidean distance becomes a monotone
        function of cosine. The default: it is what the embedding literature
        uses, and it removes the length-of-vector component that tracks how much
        sequence was pooled rather than what was in it.
    ``zscore``
        standardise each dimension. Gives every dimension equal say, which
        amplifies near-dead ones; useful for a PCA that should not be steered by
        a handful of high-variance dimensions, risky otherwise.
    """
    if normalize not in NORMALIZATIONS:
        raise ValueError(f"normalize must be one of {NORMALIZATIONS}, got {normalize!r}")
    if normalize == "none":
        return X
    if normalize == "center":
        return X - X.mean(axis=0, keepdims=True)
    if normalize == "l2":
        norms = np.linalg.norm(X, axis=1, keepdims=True)
        # A zero row is a segment that was empty for this window -- a `repeat`
        # span on a reference-allele window, say. Leave it at the origin rather
        # than dividing by zero; it is genuinely "no observation", not a point.
        return X / np.where(norms == 0, 1.0, norms)
    sd = X.std(axis=0, keepdims=True)
    return (X - X.mean(axis=0, keepdims=True)) / np.where(sd == 0, 1.0, sd)


def design(emb: Embeddings) -> pd.DataFrame:
    """Per-window metadata as a frame, with the derived columns analysis needs.

    ``locus`` is ``chrom:pos`` -- the grouping that matters most, because the
    69 samples called at one breakpoint share their flanks and are therefore
    *not* independent points. ``log_length`` is there because insertion length
    spans 52 bp to 54 kb and correlates with everything on a linear scale.
    """
    n = len(emb.vectors)
    meta = emb.meta
    frame = pd.DataFrame({"row": np.arange(n)})
    frame["chrom"] = _meta(meta, "chrom", n, "")
    frame["pos"] = _meta(meta, "pos", n, -1)
    frame["locus"] = frame["chrom"].astype(str) + ":" + frame["pos"].astype(str)
    frame["sample"] = _meta(meta, "sample", n, "")
    frame["svid"] = _meta(meta, "svid", n, "")
    frame["insert_length"] = _meta(meta, "insert_length", n, 0)
    frame["log_length"] = np.log10(frame["insert_length"].clip(lower=1))
    frame["n_fraction"] = _meta(meta, "n_fraction", n, 0.0)
    frame["cropped"] = _meta(meta, "cropped", n, False)
    return frame[list(DESIGN_COLUMNS)]


def background_index(emb: Embeddings, bg: Embeddings) -> np.ndarray:
    """For each row of ``emb``, the row of ``bg`` at the same breakpoint.

    ``-1`` where the background has no window there, which happens when the two
    runs were sharded differently or the background dropped a window on
    ``--max-n-fraction``. Callers decide whether to drop those rows or stop;
    nothing here silently pairs a locus with the wrong one.

    Matching is on ``(chrom, pos)`` alone, not on sample: the reference allele
    at a breakpoint does not depend on who was called there, which is exactly
    why ``evo-embed --background`` emits one window per distinct breakpoint
    instead of one per call.
    """
    keys = list(zip(bg.meta["chrom"].astype(str), bg.meta["pos"].astype(np.int64)))
    where = {}
    for i, key in enumerate(keys):
        where.setdefault(key, i)
    query = zip(emb.meta["chrom"].astype(str), emb.meta["pos"].astype(np.int64))
    return np.array([where.get(key, -1) for key in query], dtype=np.int64)


def delta(
    emb: Embeddings,
    bg: Embeddings,
    layer: str,
    segment: str,
    strand: str = "both",
    normalize: str = "l2",
) -> tuple[np.ndarray, np.ndarray]:
    """``alt - reference`` per window: what the insertion did, locus removed.

    Returns the difference matrix and the boolean mask of rows that had a
    background window, so the caller can subset ``design(emb)`` to match.

    Both sides are normalised *before* subtracting. With ``l2`` that makes the
    difference a chord on the unit sphere -- comparable between windows whose
    raw vectors differ in magnitude because they pooled different amounts of
    sequence. Normalising afterwards instead would throw away the size of the
    effect, which is most of the signal: a 54 kb insertion should not look like
    a 5 bp one.
    """
    index = background_index(emb, bg)
    mask = index >= 0
    if not mask.any():
        raise ValueError(
            "no window in the background run shares a breakpoint with the "
            "alt run; check they were built from the same VCF and --flank"
        )
    alt = prepare(view(emb, layer, segment, strand), normalize)
    ref = prepare(view(bg, layer, segment, strand), normalize)
    return alt[mask] - ref[index[mask]], mask


def _index(names: list[str], wanted: str, kind: str) -> int:
    try:
        return names.index(wanted)
    except ValueError:
        raise KeyError(f"no {kind} {wanted!r}; have {names}") from None


def _meta(meta: dict[str, np.ndarray], key: str, n: int, fill) -> np.ndarray:
    """A metadata column, or a constant when an older run did not store it."""
    if key in meta:
        return meta[key]
    return np.full(n, fill)
