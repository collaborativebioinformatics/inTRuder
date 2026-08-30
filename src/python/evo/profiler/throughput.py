"""Three questions about the cost of a window, and the variants that answer them.

**Where does the time go?** :func:`evo.embeddings.extract.extract_window` runs
two forward passes and then, for every layer, does
``.to(torch.float32).cpu().numpy()`` on an ``(8192, 4096)`` tensor -- 134 MB of
fp32 per layer per pass, moved across PCIe only for :func:`~evo.embeddings.extract.pool`
to reduce it to five vectors. Nine layers make that ~2.4 GB per window. If the
forward passes dominate anyway, nothing here is worth changing; if the transfer
is a fifth of the time, pooling on the device removes almost all of it. Timing
the two apart needs a ``cuda.synchronize`` between them, which is why this
cannot be measured from outside the process.

**Is there room to batch?** The earlier run peaked at 21,230 of 23,034 MiB, and
both instance types this project can launch are the same 1x L4 24 GB -- there is
no larger card to move to. But that peak *included* the per-layer fp32 staging
copies, so removing them may open enough headroom for a batch of two. A window's
forward pass and its reverse complement are the same length by construction, so
they are the one batch in this pipeline that wastes nothing on padding.

**Does batching even help?** Probably not much, and that is exactly why it is
measured. Batch size buys throughput when short sequences leave the card idle
between kernel launches. One 8192-token pass through a 7B model is ~115 TFLOPs
against an L4's ~121 TFLOPS peak, so a single sequence already saturates it and
batching can only recover launch overhead. A few percent is not worth the OOM
risk on a long unattended run; a third would be.

What is deliberately *not* measured: dataloader workers. There is no dataloader.
Window construction is the whole of the host-side cost, it happens once for the
entire shard before the model is even loaded, and :func:`evo.embeddings.extract.extract`
consumes the finished list -- so there is no per-batch host work for a worker to
overlap with. The CLI times window building anyway, to show the number rather
than assert it.

Every variant is checked against the current code's output before its timing is
believed. A faster variant that computes something else is not an optimisation,
and on-device pooling changes both the reduction order and the dtype the
accumulation happens in, so the check is not a formality.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Self

import numpy as np

from evo.embeddings.extract import (
    DEFAULT_LAYER_SET,
    LAYER_SETS,
    SEGMENT_POOLING,
    reverse_complement,
    segment_spans,
)
from evo.embeddings.windows import SEGMENTS, Window

PROFILED_LAYERS: tuple[str, ...] = LAYER_SETS[DEFAULT_LAYER_SET]
"""The layer set the run uses.

Aliased from :data:`~evo.embeddings.extract.LAYER_SETS` rather than rebuilt, so
what is profiled here is literally what ``evo-embed`` will run. Layers cost no
forward-pass time -- one pass yields every one of them -- but they do cost a
staging copy, a transfer, and their share of the output file; whether they also
cost VRAM headroom is one of the things measured here.
"""


class Timer:
    """Accumulates per-stage timings, synchronising CUDA around each stage.

    Without the synchronise every GPU stage would report the time to *enqueue*
    its kernels, and the first blocking call downstream would be charged for all
    of them -- putting the entire forward pass under the transfer's name and
    reversing the conclusion this module exists to reach.
    """

    def __init__(self, torch, device: str):
        self._torch = torch
        self._device = device
        self.stages: dict[str, list[float]] = {}

    def sync(self) -> None:
        self._torch.cuda.synchronize(self._device)

    def __call__(self, name: str) -> _Stage:
        return _Stage(self, name)

    def record(self, name: str, seconds: float) -> None:
        self.stages.setdefault(name, []).append(seconds)

    def reset(self) -> None:
        """Forget everything timed so far. Used to discard the warm-up."""
        self.stages.clear()

    def per_window(self, n_windows: int) -> dict[str, float]:
        return {k: sum(v) / n_windows for k, v in self.stages.items()}


class _Stage:
    def __init__(self, timer: Timer, name: str):
        self._timer, self._name = timer, name

    def __enter__(self) -> Self:
        self._timer.sync()
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> bool:
        self._timer.sync()
        self._timer.record(self._name, time.perf_counter() - self._t0)
        return False


def spans_for(window: Window, reverse: bool) -> list[tuple[int, int, str]]:
    """``(start, end, pooling)`` per segment, on the requested strand.

    Delegates to :func:`evo.embeddings.extract.segment_spans` rather than
    repeating it: the production paths use that one, and a profiler with its own
    copy could report agreement between two variants that were both wrong in the
    same way -- which is precisely what the comparison is supposed to rule out.
    """
    return segment_spans(window, SEGMENTS, SEGMENT_POOLING, reverse=reverse)


def pooled_on_host(tokens_by_layer: dict[str, np.ndarray], spans) -> np.ndarray:
    """Pool already-transferred token grids. What the current code does."""
    return np.stack([
        np.stack([
            np.zeros(tokens.shape[-1], dtype=np.float32) if end <= start
            else (tokens[start:end].mean(axis=0) if how == "mean" else tokens[end - 1])
            for start, end, how in spans
        ])
        for tokens in tokens_by_layer.values()
    ])


def pooled_on_device(torch, tokens_by_layer, spans) -> np.ndarray:
    """Pool on the GPU; only ``n_segments x width`` per layer crosses PCIe.

    80 KB against 134 MB, and no fp32 copy of the full token grid is ever
    allocated -- which is the part that matters for VRAM, not just for time.
    ``mean(dtype=torch.float32)`` accumulates in fp32 without materialising an
    upcast slice, so the result matches the host path to within reduction order
    while never paying its memory.
    """
    out = []
    for tokens in tokens_by_layer.values():
        vecs = []
        for start, end, how in spans:
            if end <= start:
                vecs.append(torch.zeros(tokens.shape[-1], dtype=torch.float32,
                                        device=tokens.device))
            elif how == "mean":
                vecs.append(tokens[start:end].mean(dim=0, dtype=torch.float32))
            else:
                vecs.append(tokens[end - 1].to(torch.float32))
        out.append(torch.stack(vecs))
    return torch.stack(out).cpu().numpy()


def _forward(model, torch, sequences: Sequence[str], layers, device: str):
    """One forward pass over a batch of equal-length sequences; stays on device."""
    ids = torch.tensor(
        [model.tokenizer.tokenize(s) for s in sequences], dtype=torch.int
    ).to(device)
    with torch.inference_mode():
        _, embeddings = model(ids, return_embeddings=True, layer_names=list(layers))
    return embeddings


def variant_host(embedder, torch, window, layers, timer, device):
    """What the code does today: whole token grid to the host, pool in numpy."""
    model = embedder._model
    results = []
    for reverse, seq in enumerate((window.sequence,
                                   reverse_complement(window.sequence))):
        with timer("forward"):
            emb = _forward(model, torch, [seq], layers, device)
        with timer("transfer+cast"):
            host = {k: emb[k][0].to(torch.float32).cpu().numpy() for k in layers}
        with timer("pool"):
            results.append(pooled_on_host(host, spans_for(window, bool(reverse))))
        del emb, host
    return np.concatenate(results, axis=-1)


def variant_device(embedder, torch, window, layers, timer, device):
    """Pool on the GPU; only the pooled vectors cross PCIe."""
    model = embedder._model
    results = []
    for reverse, seq in enumerate((window.sequence,
                                   reverse_complement(window.sequence))):
        with timer("forward"):
            emb = _forward(model, torch, [seq], layers, device)
        with timer("pool+transfer"):
            results.append(pooled_on_device(
                torch, {k: emb[k][0] for k in layers},
                spans_for(window, bool(reverse)),
            ))
        del emb
    return np.concatenate(results, axis=-1)


def variant_batched(embedder, torch, window, layers, timer, device):
    """Forward and reverse complement as ONE batch-2 pass, pooled on the GPU.

    The two sequences are the same window, so they are the same length and the
    batch wastes nothing on padding.
    """
    model = embedder._model
    seqs = [window.sequence, reverse_complement(window.sequence)]
    with timer("forward"):
        emb = _forward(model, torch, seqs, layers, device)
    with timer("pool+transfer"):
        results = [
            pooled_on_device(
                torch, {k: emb[k][i] for k in layers}, spans_for(window, bool(i))
            )
            for i in (0, 1)
        ]
    del emb
    return np.concatenate(results, axis=-1)


VARIANTS: dict[str, tuple] = {
    "host": (variant_host,
             "current code: whole token grid to host, pool in numpy"),
    "device": (variant_device,
               "pool on GPU, transfer only the pooled vectors"),
    "batched": (variant_batched,
                "fwd+revcomp as one batch-2 pass, pooled on GPU"),
}
"""Variant name -> (function, one-line description). ``host`` is the baseline."""


class Result(dict):
    """Per-window seconds, stage breakdown, peak MiB, and the equivalence check."""


def profile_variant(
    name, embedder, torch, windows, layers, device, warmup=1, reference=None, atol=2e-2,
):
    """Time one variant over ``windows``, after ``warmup`` untimed windows.

    The warm-up is not politeness: the first pass through a new shape pays
    allocator growth and kernel autotuning that no later pass does, and on a
    six-window sample that would land entirely on the variant unlucky enough to
    run first.

    ``reference`` is the baseline variant's output for ``windows[warmup]``. When
    given, this variant's output for the same window is compared against it and
    the result carries the largest absolute difference, so a speedup that
    quietly computes something else cannot be reported as a win.
    """
    fn, _ = VARIANTS[name]
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    timer = Timer(torch, device)

    for window in windows[:warmup]:
        fn(embedder, torch, window, layers, timer, device)
    timer.reset()

    first = None
    t0 = time.perf_counter()
    for i, window in enumerate(windows[warmup:]):
        out = fn(embedder, torch, window, layers, timer, device)
        if i == 0:
            first = out
    wall = time.perf_counter() - t0

    timed = len(windows) - warmup
    result = Result(
        variant=name,
        seconds=wall / timed,
        stages=timer.per_window(timed),
        peak_mib=torch.cuda.max_memory_allocated() / 1024**2,
        output=first,
        max_abs_diff=None,
        matches=None,
    )
    if reference is not None and first is not None:
        finite = np.isfinite(reference) & np.isfinite(first)
        diff = float(np.max(np.abs(reference[finite] - first[finite]))) if finite.any() else 0.0
        result["max_abs_diff"] = diff
        result["matches"] = bool(diff <= atol)
    return result
