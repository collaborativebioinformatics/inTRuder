"""Running Evo 2 over windows and pooling the token embeddings into vectors.

One forward pass yields one vector per token, so every segment and every layer
comes out of the same pass. The cost is the pass; the pooling is free. That is
why :func:`extract` takes *lists* of layers and pools *all* segments -- asking
for five segments across twelve layers costs exactly what asking for one costs.

Strand
------
Evo 2 is autoregressive, so a token's embedding summarises what came *before*
it and knows nothing of what follows. Arc's own ``exon_classifier`` handles this
by running the sequence and its reverse complement and concatenating the two
vectors, and the same trick is used here: every returned vector is
``concat(forward, reverse_complement)`` and therefore twice ``d_model`` wide.

Mapping a span onto the reverse strand is the one place this is easy to get
wrong. Bases ``S[a:b]`` of a length-``L`` window appear in the reverse complement
at ``[L-b, L-a)``. Under ``last`` pooling that inverts which end is read, which
is exactly the point: forward-last sees the span's 3' end with everything
upstream behind it, reverse-last sees its 5' end with everything downstream
behind it.

Pooling
-------
``mean``
    average over the span. The natural summary of a region, and what you want
    for ``left``, ``right`` and ``repeat``.
``last``
    the final token of the span. Arc uses this in ``exon_classifier``
    (``embeddings[layer][0, -1, :]``) because they classify a *position*, and it
    is the better choice for the junction spans for the same reason -- a
    breakpoint is a position, not a region.

Layers
------
The block indices in :data:`BLOCK_TYPES` were read off the ``evo2_7b``
checkpoint itself rather than taken from documentation. The three hyena variants
differ in receptive field by construction, which is what makes the choice more
than a guess: the long-filter blocks carry ``filter.log_poles``/``residues``
against a 1,048,576-step time grid and are the ones parameterised for long-range
*periodic* structure, i.e. tandem repeats; the attention blocks do content-based
global mixing and are the natural place to read *placement*.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

import numpy as np

from evo.embeddings.windows import SEGMENTS, Window

# Block types of evo2_7b, read from the checkpoint's parameter names. The cycle
# has period 7; attention sits at index 3 of each cycle.
BLOCK_TYPES: dict[str, tuple[int, ...]] = {
    "hyena_short": (0, 4, 7, 11, 14, 18, 21, 25, 28),
    "hyena_mid": (1, 5, 8, 12, 15, 19, 22, 26, 29),
    "hyena_long": (2, 6, 9, 13, 16, 20, 23, 27, 30),
    "attention": (3, 10, 17, 24, 31),
}

N_BLOCKS = 32
D_MODEL = 4096

#: Named layer sets. ``default`` spreads across depth and samples the two block
#: types with a reason to be informative here, plus the uniform MLP probe that
#: is comparable across every depth.
LAYER_SETS: dict[str, tuple[str, ...]] = {
    "default": (
        "blocks.9.mlp.l3",
        "blocks.16",
        "blocks.17",
        "blocks.23",
        "blocks.24",
        "blocks.26",
        "blocks.28.mlp.l3",
        "blocks.30",
        "blocks.31",
    ),
    "attention": tuple(f"blocks.{i}" for i in BLOCK_TYPES["attention"]),
    "long_filter": tuple(f"blocks.{i}" for i in BLOCK_TYPES["hyena_long"]),
    "uniform": tuple(f"blocks.{i}.mlp.l3" for i in range(0, N_BLOCKS, 4)),
    "arc": ("blocks.26",),  # what exon_classifier uses
}

POOLINGS = ("mean", "last")

#: Default pooling per segment: regions get ``mean``, breakpoints get ``last``.
SEGMENT_POOLING: dict[str, str] = {
    "left": "mean",
    "junction_5p": "last",
    "repeat": "mean",
    "junction_3p": "last",
    "right": "mean",
}

_COMPLEMENT = str.maketrans("ACGTUNacgtunRYSWKMBDHVryswkmbdhv",
                            "TGCAANtgcaanYRSWMKVHDByrswmkvhdb")


def reverse_complement(seq: str) -> str:
    return seq.translate(_COMPLEMENT)[::-1]


def reverse_span(start: int, end: int, length: int) -> tuple[int, int]:
    """Where ``[start, end)`` lands after reverse-complementing a length-``L``
    sequence. Bases at the front of the forward strand sit at the back here."""
    return length - end, length - start


class Embedder(Protocol):
    """Anything that turns a DNA string into per-token vectors per layer.

    Kept behind a protocol so the pooling logic is testable without a GPU: the
    tests pass a deterministic fake, the cluster passes :class:`Evo2Embedder`.
    """

    @property
    def width(self) -> int:
        """Size of one layer's per-token vector."""

    def __call__(self, sequence: str, layers: Sequence[str]) -> dict[str, np.ndarray]:
        """Return ``{layer: array of shape (len(sequence), width)}``."""


class Evo2Embedder:
    """The real thing. Imports ``evo2`` lazily so this module stays importable
    on machines that cannot install it (no CUDA, or Python 3.13)."""

    def __init__(self, model: str = "evo2_7b_base", device: str = "cuda:0"):
        try:
            from evo2 import Evo2
        except ImportError:  # pragma: no cover - cluster-only path
            raise ImportError(
                "Evo2Embedder needs the `evo2` package: it requires Linux, CUDA "
                "12.1+, flash-attn, and Python <3.13. Install with "
                "`uv sync --extra cu128 --extra embed` in a 3.12 venv."
            ) from None
        self._torch = __import__("torch")
        self._model = Evo2(model)
        self._device = device
        self.model_name = model

    @property
    def width(self) -> int:
        return D_MODEL

    def __call__(self, sequence: str, layers: Sequence[str]) -> dict[str, np.ndarray]:
        torch = self._torch
        ids = torch.tensor(
            self._model.tokenizer.tokenize(sequence), dtype=torch.int
        ).unsqueeze(0).to(self._device)
        with torch.inference_mode():
            _, embeddings = self._model(
                ids, return_embeddings=True, layer_names=list(layers)
            )
        # (batch, seq_len, width) -> (seq_len, width); cast because bf16 has no
        # numpy equivalent.
        return {
            name: embeddings[name][0].to(torch.float32).cpu().numpy()
            for name in layers
        }


class KmerEmbedder:
    """A stand-in for Evo 2 that needs no model, no GPU and no network.

    Token *i* becomes a one-hot over the *k*-mer ending at position *i*. That
    makes the pooling modes mean something real rather than shuffling noise:
    ``mean`` over a span is exactly that span's *k*-mer frequency vector, a
    classic sequence representation, and ``last`` is the *k*-mer at that
    position.

    It exists so the pipeline -- VCF reading, window construction, strand
    handling, pooling, filtering, storage, plots -- can be exercised end to end
    on a machine that cannot run Evo 2, which includes any Intel Mac (torch
    ships no macOS x86_64 wheel for Python 3.13). Results carry real sequence
    structure, so figures made with it are legible.

    It is **not a language model**: it has no context beyond *k* bases, no
    learned representation and no notion of what is likely. Nothing biological
    concluded from it transfers to Evo 2. Swap in :class:`Evo2Embedder` for
    that -- it satisfies the same protocol.
    """

    def __init__(self, k: int = 4):
        self.k = k
        self._width = 4**k
        self._index = {b: i for i, b in enumerate("ACGT")}

    @property
    def width(self) -> int:
        return self._width

    def __call__(self, sequence: str, layers: Sequence[str]) -> dict[str, np.ndarray]:
        n = len(sequence)
        out = np.zeros((n, self._width), dtype=np.float32)
        code = 0
        valid = 0
        for i, base in enumerate(sequence):
            idx = self._index.get(base.upper())
            if idx is None:  # N and IUPAC codes reset the running k-mer
                code, valid = 0, 0
                continue
            code = (code * 4 + idx) % self._width
            valid += 1
            if valid >= self.k:
                out[i, code] = 1.0
        # Every layer sees the same features; depth is what a real model adds.
        return dict.fromkeys(layers, out)


def pool(tokens: np.ndarray, start: int, end: int, how: str) -> np.ndarray:
    """Reduce ``tokens[start:end]`` to one vector.

    An empty span -- a ``repeat`` segment on a reference-allele window, or one
    cropped away entirely -- yields zeros rather than raising, so that a window
    always produces a complete, fixed-shape block of vectors.
    """
    if how not in POOLINGS:
        raise ValueError(f"unknown pooling {how!r}, expected one of {POOLINGS}")
    if end <= start:
        return np.zeros(tokens.shape[1], dtype=tokens.dtype)
    span = tokens[start:end]
    return span.mean(axis=0) if how == "mean" else span[-1]


def extract_window(
    window: Window,
    embedder: Embedder,
    layers: Sequence[str],
    segments: Sequence[str] = SEGMENTS,
    pooling: dict[str, str] | None = None,
) -> np.ndarray:
    """Vectors for one window: ``(len(layers), len(segments), 2 * width)``.

    Two passes are run -- forward and reverse complement -- and the two pooled
    vectors are concatenated, so the result is twice ``embedder.width`` wide.
    """
    pooling = pooling or SEGMENT_POOLING
    length = len(window.sequence)

    fwd = embedder(window.sequence, layers)
    rev = embedder(reverse_complement(window.sequence), layers)

    out = np.zeros((len(layers), len(segments), 2 * embedder.width), dtype=np.float32)
    for li, layer in enumerate(layers):
        for si, name in enumerate(segments):
            span = window.segments[name]
            how = pooling.get(name, "mean")
            f = pool(fwd[layer], span.start, span.end, how)
            r_start, r_end = reverse_span(span.start, span.end, length)
            r = pool(rev[layer], r_start, r_end, how)
            out[li, si] = np.concatenate([f, r])
    return out


def extract(
    windows: Iterable[Window],
    embedder: Embedder,
    layers: Sequence[str] = LAYER_SETS["default"],
    segments: Sequence[str] = SEGMENTS,
    pooling: dict[str, str] | None = None,
    max_n_fraction: float | None = 0.1,
    progress: bool = False,
) -> tuple[np.ndarray, list[Window]]:
    """Vectors for many windows: ``(n, len(layers), len(segments), 2 * width)``.

    Windows above ``max_n_fraction`` are skipped, because a window that is 40% N
    describes an assembly gap rather than a locus. The surviving windows are
    returned alongside the array so that row *i* of the array is window *i* of
    the returned list -- the input order is not preserved when anything is
    dropped, and pairing them here is what stops that from becoming a silent
    off-by-N in the metadata.
    """
    kept: list[Window] = []
    blocks: list[np.ndarray] = []

    it = windows
    if progress:
        from tqdm import tqdm

        it = tqdm(list(windows), unit="window", ncols=80)

    for window in it:
        if max_n_fraction is not None and window.n_fraction > max_n_fraction:
            continue
        blocks.append(extract_window(window, embedder, layers, segments, pooling))
        kept.append(window)

    if not blocks:
        empty = np.zeros(
            (0, len(layers), len(segments), 2 * embedder.width), dtype=np.float32
        )
        return empty, kept
    return np.stack(blocks), kept
