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

#: Layers measured to exceed float16's 65504 ceiling, so storing one ships
#: +/-inf rather than numbers. From the 2026-08-27 sweep of all 32 blocks and
#: all 32 ``mlp.l3`` in `data/evo/verify-layers3/verify.txt`; peaks are 1.1e6
#: at blocks.29 and 5.1e12 at blocks.30/31. Named here so the layer set can be
#: tested against it rather than checked by eye.
OVERFLOWS_FLOAT16: frozenset[str] = frozenset(
    {"blocks.29", "blocks.29.mlp.l3", "blocks.30", "blocks.31"}
)

#: The set `evo-embed` uses when `--layers` is not given. It must not intersect
#: :data:`OVERFLOWS_FLOAT16`: the forward pass is the expensive part, and a run
#: that silently writes inf for two of its layers has spent those hours for
#: nothing. `test_the_default_layer_set_survives_float16` enforces it.
DEFAULT_LAYER_SET = "deep"

#: Named layer sets. ``deep`` is the one that runs; the rest are structural
#: probes for asking a different question of the same forward pass.
LAYER_SETS: dict[str, tuple[str, ...]] = {
    # Eight block layers plus two MLP probes, spread across depth and ending at
    # the deepest block that still fits float16. Measured 2026-08-27 on 8 alt
    # windows and their breakpoint-matched reference windows
    # (`data/evo/verify-layers3/`): the junction/flank variance ratio -- how
    # much of a layer's spread is about the insertion rather than about which
    # locus it sits in -- rises strictly from blocks.9 to blocks.28, twenty
    # consecutive layers, then falls (33.5, 14.8, 14.8):
    #
    #     blocks.28  64.4  (rank  5)     blocks.24  18.6  (rank 12)
    #     blocks.27  45.6  (rank  9)     blocks.23  11.5  (rank 13)
    #     blocks.26  28.9  (rank 10)     blocks.17   5.1  (rank 19)
    #     blocks.25  27.5  (rank 11)     blocks.16   3.8  (rank 20)
    #
    # blocks.25 is here as the control rather than for its own ratio, which
    # ties blocks.26's. It makes 25/26/27/28 four consecutive layers across the
    # steepest part of the rise, so a re-measurement can test whether the trend
    # holds locally instead of re-arguing one adjacent pair.
    #
    # Ranks are among the 29 blocks that survive float16, and blocks.28 is only
    # 5th: blocks.0 (337), blocks.1 (206), blocks.6 (65.6) and blocks.5 (64.5)
    # outrank it. All four are discarded for one reason -- that shallow, their
    # flank denominator is the numerical noise floor (blocks.0's flank delta is
    # 4.3e-05; blocks.4-8 sit at flank variance ~1e-06) rather than a measured
    # background, so a large ratio there says nothing about junction signal.
    # The ratio is only interpretable where the flank has been processed enough
    # to have a real background, which is blocks.9 on.
    #
    # Layers are nearly free: one forward pass yields every one of them, so the
    # cost is storage -- 0.63 GiB per layer across the alt and reference runs of
    # the full callset, 6.3 GiB for these ten, against the ~22 GPU-hours it
    # costs to get a skipped layer back. That asymmetry, not the size of the
    # effect, is why the deep end is taken whole. It does not extend
    # indefinitely: `store.load` reads `vectors` eagerly, so all 29 fp16-safe
    # blocks would be a 13.6 GiB alt array on the laptop side.
    #
    # blocks.29/30/31 are left out because they overflow float16 -- 1.1e6,
    # 5.1e12, 5.1e12 against a 65504 ceiling. That is a storage limit, not a
    # verdict on their signal: blocks.29's ratio (33.5) beats blocks.26's, and
    # blocks.31 is the deepest attention block. Storing bfloat16 would recover
    # blocks.29; blocks.30/31 are the pair `Evo2Embedder.pooled` diverges on,
    # so they need more than a wider exponent.
    #
    # CAUTION, three things:
    #   * n = 8. Twenty layers of strict rise is not something noise produces,
    #     but 64.4-vs-45.6 is a single adjacent pair, and both halves of it
    #     jumped ~5e4 from blocks.27 in the same step (junc var 0.208 ->
    #     1.57e4, flank var 4.6e-03 -> 244). Do not read blocks.28 > blocks.27
    #     off this run; re-measure on a few hundred windows first.
    #   * blocks.28 reaches max |x| 2416, against 996 for the deepest layer
    #     below it and 1.1e6 at blocks.29 -- the cliff is one block away.
    #     `store.save` reports per-layer overflow, so a run that crosses it
    #     says so rather than shipping inf; check that warning.
    #   * `Evo2Embedder.pooled` was checked against the host path on the seven
    #     shallower layers only (2.7e-4), and the layers it diverges on are the
    #     large-activation ones. blocks.28 is the first layer past that
    #     validated range. The fp32 accumulation has ample headroom at 2.4e3,
    #     but it is unmeasured.
    #
    # blocks.28 is not a second, independent read alongside blocks.28.mlp.l3.
    # A block returns the post-MLP residual stream, so blocks.28 contains
    # blocks.28.mlp.l3 as a summand -- and their max |x| is the same 2416, i.e.
    # the block's extremes *are* the MLP term already being stored. Keep both
    # for the residual-vs-update contrast, not as two measurements.
    "deep": (
        "blocks.9.mlp.l3",
        "blocks.16",
        "blocks.17",
        "blocks.23",
        "blocks.24",
        "blocks.25",
        "blocks.26",
        "blocks.27",
        "blocks.28",
        "blocks.28.mlp.l3",
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


class PooledEmbedder(Protocol):
    """An :class:`Embedder` that can also pool spans without leaving the device.

    Optional, and checked for by :func:`extract_window` rather than required,
    because the whole point of :class:`Embedder` is that a fake with no GPU can
    stand in for Evo 2. A fake has nothing to gain here -- its "device" is the
    host -- so it simply does not implement this and gets the ordinary path.
    """

    def pooled(
        self,
        sequence: str,
        layers: Sequence[str],
        spans: Sequence[tuple[int, int, str]],
    ) -> np.ndarray:
        """Return ``(len(layers), len(spans), width)``, pooled on the device."""


def segment_spans(
    window: Window,
    segments: Sequence[str],
    pooling: dict[str, str],
    reverse: bool = False,
) -> list[tuple[int, int, str]]:
    """``(start, end, how)`` per segment, on the requested strand.

    Mapping a span onto the reverse strand is the one part of this that is easy
    to get wrong, so it lives in one place that every path calls -- the host
    path, the device path, and the profiler that compares them. Two
    implementations could otherwise agree with each other while both being
    wrong, which is the failure an equivalence check cannot catch.
    """
    length = len(window.sequence)
    spans = []
    for name in segments:
        span = window.segments[name]
        how = pooling.get(name, "mean")
        if how not in POOLINGS:
            raise ValueError(f"unknown pooling {how!r}, expected one of {POOLINGS}")
        start, end = (
            reverse_span(span.start, span.end, length) if reverse
            else (span.start, span.end)
        )
        spans.append((start, end, how))
    return spans


class Evo2Embedder:
    """The real thing. Imports ``evo2`` lazily so this module stays importable
    on machines that cannot install it (no CUDA, or Python 3.13).

    The Transformer Engine warning is expected -- do not "fix" it
    ------------------------------------------------------------

    Every 7B run prints, once, at load::

        UserWarning: Transformer Engine not installed. Falling back to bf16
        projections (use_fp8_input_projections=False).

    ``evo2/configs/evo2-7b-8k.yml`` ships ``use_fp8_input_projections: True``,
    so evo2 0.6.0 emits this whenever TE is absent. For a *7b* checkpoint it
    then sets the flag to False and continues; for 1b/20b/40b the same branch
    raises ImportError instead, because those need FP8 for numerical accuracy
    (``evo2/models.py``, both load paths). bf16 on 7B is the supported
    configuration, not a degraded one, and the warning is the model telling you
    it took that path.

    Installing TE is also the wrong lever for *speed*, which is what it looks
    like it promises. The flag covers only the input projections, whereas 27 of
    this checkpoint's 32 layers are Hyena convolutions (``hcl``/``hcm``/``hcs``
    layer indices in the config) whose cost is the FFT, not the projection --
    only 5 layers are attention. ``use_kernels`` is the flag that targets the
    other 27.
    """

    def __init__(
        self,
        model: str = "evo2_7b_base",
        device: str = "cuda:0",
        use_kernels: bool = False,
    ):
        """``use_kernels`` enables Vortex's opt-in Triton HC{S,M,L} kernels.

        Those are the Hyena short/medium/long convolutions -- 27 of 32 layers,
        and the memory-bandwidth-bound half of the forward pass: on an L4 the
        memory controller runs at 91-95% during those phases and the SM clock
        collapses to ~870-930 MHz, because the card spends one fixed 72 W budget
        on either DRAM traffic or clocks, never both.

        Off by default, and deliberately so. evo2's own docstring says "always
        validate outputs when enabling them", because vortex falls back to the
        standard path silently when a kernel is unavailable -- so a run can
        differ from the baseline, or fail to differ from it, without saying
        which. Requires ``vtx>=1.1.0`` (the lock pins exactly 1.1.0). Check the
        vectors with ``python -m evo.profiler`` before trusting a run made with
        it.
        """
        try:
            from evo2 import Evo2
        except ImportError:  # pragma: no cover - cluster-only path
            raise ImportError(
                "Evo2Embedder needs the `evo2` package: it requires Linux, CUDA "
                "12.1+, flash-attn, and Python <3.13. Run "
                "`scripts/setup-gpu-worker.sh`, which syncs a 3.12 venv and then "
                "adds the matching prebuilt flash-attn wheel -- flash-attn is not "
                "in uv.lock, and vortex imports it eagerly, so a plain `uv sync` "
                "is not enough. Afterwards invoke `.venv/bin/evo-embed` directly; "
                "`uv run` resyncs to the lock and uninstalls flash-attn."
            ) from None
        self._torch = __import__("torch")
        self._model = Evo2(model, use_kernels=use_kernels)
        self._device = device
        self.model_name = model
        self.use_kernels = use_kernels

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

    def _forward(self, sequence: str, layers: Sequence[str]):
        torch = self._torch
        ids = torch.tensor(
            self._model.tokenizer.tokenize(sequence), dtype=torch.int
        ).unsqueeze(0).to(self._device)
        with torch.inference_mode():
            _, embeddings = self._model(
                ids, return_embeddings=True, layer_names=list(layers)
            )
        return embeddings

    def pooled(
        self,
        sequence: str,
        layers: Sequence[str],
        spans: Sequence[tuple[int, int, str]],
    ) -> np.ndarray:
        """Pool on the GPU, so only the pooled vectors cross PCIe.

        Measured on an L4 (2026-08-27, evo.profiler, 7 layers): this removes
        0.92 of the 7.89 s a window used to take, which is 12% of the run and
        about two hours of the full callset. ``__call__`` moves the entire
        ``(8192, 4096)`` token grid to the host as float32 -- 134 MB per layer
        per pass -- for :func:`pool` to reduce it to five vectors; this sends
        ``len(spans) x width`` per layer instead, around 80 KB.

        ``mean(dtype=torch.float32)`` accumulates in fp32 without materialising
        an upcast copy of the slice, so the vectors match the host path to
        2.7e-4 -- float16 storage noise. That was measured over the seven
        layers up to ``blocks.26``, not over ``blocks.27``/``blocks.28``. They
        do *not* match on ``blocks.30``/``blocks.31``, whose activations are
        large enough that the two reduction orders diverge outright; those are
        the layers :data:`OVERFLOWS_FLOAT16` names and ``deep`` leaves out.
        """
        torch = self._torch
        embeddings = self._forward(sequence, layers)
        out = []
        for name in layers:
            tokens = embeddings[name][0]
            vectors = []
            for start, end, how in spans:
                if end <= start:
                    vectors.append(torch.zeros(tokens.shape[-1],
                                               dtype=torch.float32,
                                               device=tokens.device))
                elif how == "mean":
                    vectors.append(tokens[start:end].mean(dim=0, dtype=torch.float32))
                else:
                    vectors.append(tokens[end - 1].to(torch.float32))
            out.append(torch.stack(vectors))
        return torch.stack(out).cpu().numpy()


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

    An embedder that can pool on its own device (:class:`PooledEmbedder`) is
    asked to, because the alternative is moving every token of every layer to
    the host only to throw all but a handful of positions away -- 12% of the
    total run time on an L4. The two paths are held to the same numbers by
    :mod:`evo.profiler`, which runs both and compares.
    """
    pooling = pooling or SEGMENT_POOLING
    fwd_spans = segment_spans(window, segments, pooling, reverse=False)
    rev_spans = segment_spans(window, segments, pooling, reverse=True)

    pooled = getattr(embedder, "pooled", None)
    if pooled is not None:
        return np.concatenate(
            [
                pooled(window.sequence, layers, fwd_spans),
                pooled(reverse_complement(window.sequence), layers, rev_spans),
            ],
            axis=-1,
        ).astype(np.float32, copy=False)

    fwd = embedder(window.sequence, layers)
    rev = embedder(reverse_complement(window.sequence), layers)

    out = np.zeros((len(layers), len(segments), 2 * embedder.width), dtype=np.float32)
    for li, layer in enumerate(layers):
        for si, (f_span, r_span) in enumerate(zip(fwd_spans, rev_spans)):
            f = pool(fwd[layer], f_span[0], f_span[1], f_span[2])
            r = pool(rev[layer], r_span[0], r_span[1], r_span[2])
            out[li, si] = np.concatenate([f, r])
    return out


def extract(
    windows: Iterable[Window],
    embedder: Embedder,
    layers: Sequence[str] = LAYER_SETS[DEFAULT_LAYER_SET],
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

    # Filter BEFORE the bar, so it counts only windows that are actually
    # embedded. Wrapping the unfiltered list made skipped windows tick
    # instantly: the first benchmark reported 0.97 s/window for a run that
    # embedded 3 of 40, a 10x error, and on a 16-hour run the ETA is wrong for
    # the whole of it. The generator keeps the no-progress path lazy; `list` is
    # only forced when a total has to be known.
    todo = (
        w for w in windows
        if max_n_fraction is None or w.n_fraction <= max_n_fraction
    )
    if progress:
        from tqdm import tqdm

        todo = tqdm(list(todo), unit="window", ncols=80)

    for window in todo:
        blocks.append(extract_window(window, embedder, layers, segments, pooling))
        kept.append(window)

    if not blocks:
        empty = np.zeros(
            (0, len(layers), len(segments), 2 * embedder.width), dtype=np.float32
        )
        return empty, kept
    return np.stack(blocks), kept
