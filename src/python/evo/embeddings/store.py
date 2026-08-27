"""Writing extracted vectors to disk and reading them back.

The two halves of this project run on different machines and different Python
versions, so this file is the interface between them: the cluster writes it, a
laptop reads it. That makes the metadata as important as the vectors -- a bare
array of numbers with no record of which layer, which segment, or which sample
each row came from is not analysable, and the settings that produced it cannot
be reconstructed from the numbers.

Layout of the ``.npz``::

    vectors    float16  (n_windows, n_layers, n_segments, 2 * d_model)
    layers     str      (n_layers,)
    segments   str      (n_segments,)
    chrom      str      (n_windows,)     per-window metadata follows
    pos        int64    (n_windows,)
    sample     str      (n_windows,)
    svid       str      (n_windows,)
    insert_length int64 (n_windows,)     pre-crop, the length covariate
    n_fraction float32  (n_windows,)
    cropped    bool     (n_windows,)

Vectors are stored as float16. At 4096 dims doubled by the strand concatenation
that is 16 KB per vector, so a full run -- ~6000 windows x 10 layers x 5 segments
-- is about 6 GB in float16 and 12 GB in float32. The precision lost is well
below the noise in any downstream clustering.
"""

from __future__ import annotations

import sys
from typing import NamedTuple

import numpy as np

from evo.embeddings.windows import Window


class Embeddings(NamedTuple):
    """Vectors plus everything needed to interpret them."""

    vectors: np.ndarray
    layers: list[str]
    segments: list[str]
    meta: dict[str, np.ndarray]
    attrs: dict[str, str]

    def __len__(self) -> int:
        return len(self.vectors)

    def view(self, layer: str, segment: str) -> np.ndarray:
        """The ``(n_windows, 2 * d_model)`` matrix for one layer and segment.

        This is the unit of analysis: clustering mixes nothing across layers or
        segments, it asks what one layer's view of one segment looks like.
        """
        try:
            li = self.layers.index(layer)
        except ValueError:
            raise KeyError(f"no layer {layer!r}; have {self.layers}") from None
        try:
            si = self.segments.index(segment)
        except ValueError:
            raise KeyError(f"no segment {segment!r}; have {self.segments}") from None
        return self.vectors[:, li, si, :]


def _to_float16(vectors: np.ndarray, layers: list[str]) -> tuple[np.ndarray, list[str]]:
    """Cast to float16 and say which layers did not survive it.

    The 2026-08-27 run shipped ``blocks.30`` and ``blocks.31`` as ~100% +/-inf
    and nothing said so: the cast is silent, the file loads, and the loss only
    surfaces much later as an all-NaN projection. 22% of that run's array was
    unusable and the GPU hours that produced it were spent.

    So the overflow is counted at the one moment it is introduced, named per
    layer -- the granularity at which it actually happens, since it is a
    property of a block's activation scale -- and recorded in the file's own
    attributes as well as on stderr. A reader can then ask what it is holding
    instead of inferring it. The values are still written: they are what the
    model produced at that precision, and a caller who wants them intact should
    drop the layer (``--layers deep``) rather than have this function guess.
    """
    # numpy's own "overflow encountered in cast" says nothing about which layer
    # overflowed or by how much, and it fires once per call regardless. The
    # report below replaces it rather than competing with it.
    with np.errstate(over="ignore"):
        stored = vectors.astype(np.float16)
    lost = np.isfinite(vectors) & ~np.isfinite(stored)
    if not lost.any():
        return stored, []
    overflowed = []
    for i, layer in enumerate(layers):
        fraction = float(lost[:, i].mean())
        if fraction:
            overflowed.append(layer)
            print(
                f"WARNING: {layer}: {100 * fraction:.1f}% of values exceed "
                f"float16 and are stored as +/-inf (max |x| {np.abs(vectors[:, i]).max():.3g})",
                file=sys.stderr,
            )
    # Naming the offending layers, not just the set to use: `--layers` also
    # takes a literal list, and that is how a run gets here in the first place.
    print(f"WARNING: re-run without {', '.join(overflowed)} "
          f"-- --layers deep is the deepest set that survives float16",
          file=sys.stderr)
    return stored, overflowed


def save(
    path: str,
    vectors: np.ndarray,
    windows: list[Window],
    layers: list[str],
    segments: list[str],
    samples: list[str] | None = None,
    svids: list[str] | None = None,
    attrs: dict[str, str] | None = None,
) -> None:
    """Write vectors and per-window metadata to ``path``.

    ``vectors`` must have one row per window; the mismatch is checked here
    rather than left to surface as a confusing index error during analysis.
    """
    if len(vectors) != len(windows):
        raise ValueError(
            f"vectors has {len(vectors)} rows but {len(windows)} windows were given"
        )
    if vectors.ndim != 4:
        raise ValueError(f"expected 4-D vectors, got shape {vectors.shape}")
    if vectors.shape[1:3] != (len(layers), len(segments)):
        raise ValueError(
            f"vectors axes {vectors.shape[1:3]} do not match "
            f"{len(layers)} layers x {len(segments)} segments"
        )

    n = len(windows)
    stored, overflowed = _to_float16(vectors, layers)
    payload = {
        "vectors": stored,
        "layers": np.asarray(layers, dtype=object),
        "segments": np.asarray(segments, dtype=object),
        "chrom": np.asarray([w.chrom for w in windows], dtype=object),
        "pos": np.asarray([w.ins_coord for w in windows], dtype=np.int64),
        "insert_length": np.asarray([w.insert_length for w in windows], dtype=np.int64),
        "n_fraction": np.asarray([w.n_fraction for w in windows], dtype=np.float32),
        "cropped": np.asarray([w.cropped for w in windows], dtype=bool),
        "sample": np.asarray(samples if samples is not None else [""] * n, dtype=object),
        "svid": np.asarray(svids if svids is not None else [""] * n, dtype=object),
        "_attrs": np.asarray(
            sorted({
                "overflowed_layers": ",".join(overflowed),
                **(attrs or {}),
            }.items()),
            dtype=object,
        ),
    }
    np.savez_compressed(path, **payload)


def load(path: str) -> Embeddings:
    """Read back what :func:`save` wrote."""
    with np.load(path, allow_pickle=True) as z:
        attrs = {k: v for k, v in z["_attrs"]}
        # Every key, unconditionally: a file missing one was written by
        # something other than `save`, and filling a default here would put
        # fabricated positions and lengths into the analysis silently.
        meta = {
            k: z[k]
            for k in ("chrom", "pos", "sample", "svid", "insert_length",
                      "n_fraction", "cropped")
        }
        return Embeddings(
            vectors=z["vectors"],
            layers=[str(x) for x in z["layers"]],
            segments=[str(x) for x in z["segments"]],
            meta=meta,
            attrs=attrs,
        )
