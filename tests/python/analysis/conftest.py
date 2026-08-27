"""Synthetic embedding runs with known structure.

The fixtures build vectors whose answer is known in advance, so a test can
assert what a method *found* rather than that it ran. The design mirrors the
real data: several samples per locus, flanks that are constant within a locus,
junctions that are not, and one layer deliberately full of ``inf`` to stand in
for the float16 overflow that made ``blocks.30``/``blocks.31`` unusable.
"""

from __future__ import annotations

import numpy as np
import pytest

from evo.embeddings.store import Embeddings

LAYERS = ["blocks.16", "blocks.26", "blocks.31"]
SEGMENTS = ["left", "junction_5p", "repeat"]

N_LOCI = 6
N_SAMPLES = 5
WIDTH = 16  # 2 * d_model, small enough to be fast


def _run(seed: int = 0, background: bool = False) -> Embeddings:
    rng = np.random.default_rng(seed)
    if background:
        loci = [("chr1", 1000 + 100 * i) for i in range(N_LOCI)]
        samples = [""] * N_LOCI
        keys = loci
    else:
        keys = [("chr1", 1000 + 100 * i)
                for i in range(N_LOCI) for _ in range(N_SAMPLES)]
        samples = [f"S{j}" for _ in range(N_LOCI) for j in range(N_SAMPLES)]

    n = len(keys)
    vectors = np.zeros((n, len(LAYERS), len(SEGMENTS), WIDTH), dtype=np.float32)
    locus_code = np.array([(pos - 1000) // 100 for _, pos in keys])

    # `left` depends only on the locus -- the real flank behaviour, and shared
    # between the alt and background runs, because the reference flanks around a
    # breakpoint are the same sequence whichever allele sits between them. That
    # is what makes `alt - reference` cancel on this segment.
    flank = np.random.default_rng(999).normal(size=(N_LOCI, WIDTH))
    # `junction_5p` carries a locus part plus a per-row part, so it is the only
    # segment where anything sample-specific can be recovered.
    for li in range(len(LAYERS)):
        vectors[:, li, 0, :] = flank[locus_code]
        vectors[:, li, 1, :] = (
            flank[locus_code] * 0.2 + rng.normal(size=(n, WIDTH))
        )
        vectors[:, li, 2, :] = rng.normal(size=(n, WIDTH)) * 0.1

    # The overflowed layer.
    vectors[:, LAYERS.index("blocks.31")] = np.inf

    lengths = rng.integers(50, 500, size=n) if not background else np.zeros(n, int)
    return Embeddings(
        vectors=vectors.astype(np.float16),
        layers=list(LAYERS),
        segments=list(SEGMENTS),
        meta={
            "chrom": np.array([c for c, _ in keys], dtype=object),
            "pos": np.array([p for _, p in keys], dtype=np.int64),
            "sample": np.array(samples, dtype=object),
            "svid": np.array([f"v{i}" for i in range(n)], dtype=object),
            "insert_length": np.asarray(lengths, dtype=np.int64),
            "n_fraction": np.zeros(n, dtype=np.float32),
            "cropped": np.zeros(n, dtype=bool),
        },
        attrs={
            "format_version": "1", "model": "fake", "flank": "3584",
            "junction": "64", "repeat_crop": "1024", "pooling": "x=mean",
        },
    )


@pytest.fixture
def run():
    """An alt-allele run: 6 loci x 5 samples."""
    return _run(seed=0)


@pytest.fixture
def background():
    """The matching reference-allele run: one window per locus."""
    return _run(seed=1, background=True)


@pytest.fixture
def save_run():
    """Write an :class:`Embeddings` to a path.

    A fixture rather than an importable helper: pytest runs this suite in
    importlib mode (see `[tool.pytest.ini_options]`), so `conftest` is not on
    the path to import from.
    """
    return _save


@pytest.fixture
def npz(tmp_path, run):
    """The alt run written to disk, for the CLI tests."""
    path = tmp_path / "run.npz"
    _save(path, run)
    return str(path)


@pytest.fixture
def background_npz(tmp_path, background):
    """The matching reference-allele run on disk."""
    path = tmp_path / "background.npz"
    _save(path, background)
    return str(path)


def _save(path, emb: Embeddings) -> None:
    """Write an :class:`Embeddings` back out in the on-disk layout."""
    payload = {
        "vectors": emb.vectors,
        "layers": np.asarray(emb.layers, dtype=object),
        "segments": np.asarray(emb.segments, dtype=object),
        "_attrs": np.asarray(sorted(emb.attrs.items()), dtype=object),
        **emb.meta,
    }
    np.savez_compressed(path, **payload)


def _rebuild(emb: Embeddings, **changes) -> Embeddings:
    """Like ``NamedTuple._replace``, which does not work here.

    ``Embeddings.__len__`` returns the *window* count, and ``_replace`` checks
    its result with ``len()``, so it raises ``Expected 5 arguments, got 30`` on
    any run with more than five windows. Constructing the tuple directly sidesteps
    it.
    """
    fields = {
        "vectors": emb.vectors, "layers": emb.layers, "segments": emb.segments,
        "meta": emb.meta, "attrs": emb.attrs,
    }
    return Embeddings(**{**fields, **changes})


@pytest.fixture
def rebuild():
    return _rebuild


@pytest.fixture
def subset():
    """A row slice of a run: vectors and every metadata column together."""
    def take(emb: Embeddings, rows) -> Embeddings:
        return _rebuild(
            emb,
            vectors=emb.vectors[rows],
            meta={k: v[rows] for k, v in emb.meta.items()},
        )
    return take
