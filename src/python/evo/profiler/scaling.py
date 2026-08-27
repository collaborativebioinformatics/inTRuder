"""Why does one forward pass cost seconds, and what would actually make it cheaper?

:mod:`evo.profiler.throughput` answers "where does a window's time go" and, once
the PCIe transfer was removed, the answer became "all of it is the forward
pass". That is where this module starts. 6.87 s/window is 229 TFLOPs of arithmetic
(two 8192-token passes through a 7B model) against an L4's ~121 TFLOPS peak,
which is ~28% of the card. Low enough to be worth asking whether something is
wrong, high enough that the answer is probably no -- so measure instead of
arguing.

Three things are worth knowing before spending more GPU time, and none of them
can be reasoned out from the outside:

**Does cost scale linearly with sequence length?** It should. A forward pass is
~2 x params x tokens, and flash-attn keeps the five attention blocks from
turning that quadratic. If measured time instead grows faster than the token
count, attention has fallen back to a materialised N x N matrix and the fix is
an environment problem worth far more than any tuning. If it *is* linear, then
tokens are the price and the flanks are the place to look -- they are 7,168 of
every window's 7,168-8,192 tokens.

**How much of the card are we actually using?** Reported as achieved TFLOP/s and
as a fraction of the device's peak. Short sequences are launch-bound and will
look terrible; the number to read is where it plateaus.

**Would a smaller checkpoint do?** Evo 2 ships 1B, 7B and 40B. Cost is roughly
linear in parameters, so ``evo2_1b_base`` is ~7x cheaper per window -- the
single largest lever available, and the one that costs nothing but accuracy.
Whether that accuracy matters is a question about the *analysis*, not the
extraction, so this only measures the speed and leaves the choice open.

What this deliberately does not do is change any default. It prints numbers.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

#: Sequence lengths swept by default.
#:
#: They start at 2048, not 512, because vortex's packed flash-attn raises
#: ``ValueError: vector::reserve`` on short sequences -- measured 2026-08-27,
#: which killed a sweep on its very first length. Nothing in this project ever
#: embeds a short window (the smallest real one is 7,168 tokens), so the short
#: end was only ever there to show launch overhead and is not worth a crash.
#:
#: The point of the remaining spread is the *shape*: cost should be linear in
#: tokens, so 8192 should cost 4x what 2048 does. Materially more means a term
#: that is not linear -- attention building an N x N matrix. Materially less
#: means the short end is launch-bound and only the plateau should be read.
#: This is also the flank measurement: flanks are 7,168 of every window's
#: 7,168-8,192 tokens, so what a shorter window would save is read straight off
#: this table.
DEFAULT_LENGTHS: tuple[int, ...] = (2048, 3072, 4096, 6144, 8192)

#: Peak dense bf16 throughput, TFLOPS, for the cards this project can meet.
#: Used only to turn achieved FLOP/s into a percentage; an unknown device just
#: reports the raw rate.
PEAK_TFLOPS: dict[str, float] = {
    "NVIDIA L4": 121.0,
    "NVIDIA A10G": 125.0,
    "NVIDIA A100": 312.0,
    "NVIDIA H100": 989.0,
}


def peak_tflops(device_name: str) -> float | None:
    for known, peak in PEAK_TFLOPS.items():
        if known in device_name:
            return peak
    return None


def describe_model(embedder, torch) -> dict:
    """Parameter count, dtypes and attention backend of a loaded Evo 2.

    Reported because the arithmetic below is only meaningful next to them: a
    "7B" model that turned out to hold fp32 weights, or one whose attention had
    quietly fallen back, would explain a low number immediately and cannot be
    seen from a stopwatch.
    """
    info: dict = {}
    module = None
    for attr in ("model", "_model", "module"):
        candidate = getattr(embedder._model, attr, None)
        if hasattr(candidate, "parameters"):
            module = candidate
            break
    if module is None and hasattr(embedder._model, "parameters"):
        module = embedder._model

    if module is not None:
        params = list(module.parameters())
        info["parameters"] = sum(p.numel() for p in params)
        counts: dict[str, int] = {}
        for p in params:
            counts[str(p.dtype)] = counts.get(str(p.dtype), 0) + p.numel()
        info["dtypes"] = counts
    else:
        info["parameters"] = None
        info["dtypes"] = {}

    try:
        import flash_attn

        info["flash_attn"] = getattr(flash_attn, "__version__", "present")
    except ImportError:
        info["flash_attn"] = None
    return info


def time_forward(
    embedder,
    torch,
    length: int,
    layers: Sequence[str],
    device: str,
    repeats: int = 3,
) -> dict:
    """Time one forward pass of ``length`` tokens, best of ``repeats``.

    Best-of rather than mean: we want the cost of the work, and any slower run
    is some other tenant of the machine or an allocator growth event, not the
    model. One untimed pass first, for the same reason.
    """
    sequence = "ACGT" * (length // 4 + 1)
    sequence = sequence[:length]
    times = []
    for i in range(repeats + 1):
        torch.cuda.synchronize(device)
        t0 = time.perf_counter()
        ids = torch.tensor(
            [embedder._model.tokenizer.tokenize(sequence)], dtype=torch.int
        ).to(device)
        with torch.inference_mode():
            embedder._model(ids, return_embeddings=True, layer_names=list(layers))
        torch.cuda.synchronize(device)
        if i:  # discard the warm-up
            times.append(time.perf_counter() - t0)
    return {"length": length, "seconds": min(times)}


def sweep(
    embedder,
    torch,
    layers: Sequence[str],
    device: str,
    lengths: Sequence[int] = DEFAULT_LENGTHS,
    parameters: int = 7_000_000_000,
    repeats: int = 3,
) -> list[dict]:
    """Time a forward pass at each length and derive the rate it implies."""
    peak = peak_tflops(torch.cuda.get_device_name(0))
    rows = []
    previous = None
    for length in lengths:
        try:
            row = time_forward(embedder, torch, length, layers, device, repeats)
        except Exception as exc:  # noqa: BLE001 - a sweep must survive one bad point
            # Deliberately broad. A sweep exists to find where the cost curve
            # bends, and one length that the stack refuses is a data point, not
            # a reason to discard the other four and the GPU boot that paid for
            # them -- which is exactly what happened on 2026-08-27, when
            # `ValueError: vector::reserve` from packed flash-attn at 512 tokens
            # took down the whole run before it measured anything.
            torch.cuda.empty_cache()
            rows.append({
                "length": length,
                "seconds": None,
                "error": f"{type(exc).__name__}: {str(exc).splitlines()[0][:80]}",
            })
            continue
        flops = 2 * parameters * length
        row["tokens_per_s"] = length / row["seconds"]
        row["tflops"] = flops / row["seconds"] / 1e12
        row["mfu"] = (row["tflops"] / peak) if peak else None
        # The diagnostic: doubling the tokens should double the time. Much more
        # than 2x means a term that is not linear in sequence length.
        row["ratio"] = (row["seconds"] / previous) if previous else None
        previous = row["seconds"]
        rows.append(row)
    return rows
