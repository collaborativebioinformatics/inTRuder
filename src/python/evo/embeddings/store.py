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
that is 16 KB per vector, so a full run -- ~6000 windows x 9 layers x 5 segments
-- is about 4 GB in float16 and 8 GB in float32. The precision lost is well
below the noise in any downstream clustering.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np

from evo.embeddings.windows import Window

# Bumped when the layout changes in a way that older readers cannot handle.
FORMAT_VERSION = 1


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
    payload = {
        "vectors": vectors.astype(np.float16),
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
            sorted({"format_version": str(FORMAT_VERSION), **(attrs or {})}.items()),
            dtype=object,
        ),
    }
    np.savez_compressed(path, **payload)


def load(path: str) -> Embeddings:
    """Read back what :func:`save` wrote."""
    with np.load(path, allow_pickle=True) as z:
        attrs = {k: v for k, v in z["_attrs"]}
        meta = {
            k: z[k]
            for k in ("chrom", "pos", "sample", "svid", "insert_length",
                      "n_fraction", "cropped")
            if k in z
        }
        return Embeddings(
            vectors=z["vectors"],
            layers=[str(x) for x in z["layers"]],
            segments=[str(x) for x in z["segments"]],
            meta=meta,
            attrs=attrs,
        )
