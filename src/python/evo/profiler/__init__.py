"""Measuring what an extraction run costs, so the optimisation is the real one.

The full callset is 8,177 windows. At the throughput measured on 2026-08-27 --
9.65 s/window on one L4 -- that is ~22 GPU-hours, which makes a 20% saving worth
four hours of rented time and an afternoon of looking for it. It also makes a
*wrong* guess about where the time goes expensive: the obvious levers on a
torch pipeline are batch size and dataloader workers, and neither one is
necessarily the lever here.

This package answers that empirically rather than by assumption, on the only
machine that can answer it. It writes no embeddings; use
:mod:`evo.embeddings` for that.

    .venv/bin/python -m evo.profiler calls.vcf hg38.fasta

See :mod:`evo.profiler.throughput` for what is measured and why those three
things and not others.
"""

from evo.profiler.throughput import (
    FINITE_LAYERS,
    VARIANTS,
    Timer,
    pooled_on_device,
    profile_variant,
)

__all__ = [
    "FINITE_LAYERS",
    "VARIANTS",
    "Timer",
    "pooled_on_device",
    "profile_variant",
]
