"""``python -m evo.embeddings`` -- embed the reference genome *and* the samples.

    python -m evo.embeddings calls.vcf hg38.fasta out/

writes two files into ``out/``:

===================  ==========================================================
``reference.npz``    the **reference allele** at each distinct breakpoint --
                     the same flanks with no insertion. One window per
                     ``(chrom, pos)``, because the reference does not depend on
                     who was called there.
``alt.npz``          each **sample's** insertion allele. One window per call,
                     labelled with ``sample`` and ``svid``.
===================  ==========================================================

Why this exists rather than two ``evo-embed`` invocations
---------------------------------------------------------

Because the first full attempt shipped only half the job. ``evo-embed`` writes
one allele to one file, so producing the pair means remembering to run it twice
with ``--background`` the second time, and a run that forgets is indistinguishable
from a complete one until the analysis returns nothing: every axis of the alt
run is a *locus* axis (bias-corrected eta-sq 0.77-0.998 on the benchmark slice),
because 87.5% of every window is reference sequence. Subtracting the
breakpoint-matched reference allele is what cancels that, and it is not optional.
Making one command produce both makes the control impossible to omit.

It is also cheaper. Evo 2 is loaded **once** for both alleles -- a 13 GB
first-time checkpoint fetch and ~10 s of warm load that a second process would
pay again -- and the two passes share one open FASTA handle.

What "the reference genome" means here
--------------------------------------

Breakpoint-matched windows, not hg38 end to end. Embedding the whole genome at
this window size is ~378k windows, about 1,000 L4-hours, and answers a question
nobody asked: the comparison needs the reference *at the loci that were called*,
which is 2,124 windows for the 6,127 calls in the working VCF (2.88 calls per
breakpoint) -- roughly 5.7 h against 16.3 h for the alt half.

Note that an alt window already contains reference sequence, so ``left`` and
``right`` are effectively reference embeddings even in ``alt.npz`` (measured:
removing the per-locus mean leaves <10^-5 of left-forward variance). What no alt
window can give you is the reference *junction* -- a span straddling the
breakpoint with reference on both sides -- because an alt junction contains
inserted bases by construction. That span is the control, and only
``reference.npz`` has it.

Ordering and sharding
---------------------

The reference half runs first. It is about a third of the cost, so an ephemeral
worker that dies mid-run leaves behind the half that is expensive to notice
missing and cheap to redo, and any mistake in the flags surfaces on the cheap
pass rather than after 16 hours of the expensive one.

``--offset``/``--limit`` shard exactly as they do in ``evo-embed``, and the
shard range goes into the file name so several shards can share one output
directory without overwriting each other::

    python -m evo.embeddings calls.vcf hg38.fa out/ --offset 0    --limit 2000
    python -m evo.embeddings calls.vcf hg38.fa out/ --offset 2000 --limit 2000
    # out/reference.0-2000.npz  out/alt.0-2000.npz
    # out/reference.2000-4000.npz  out/alt.2000-4000.npz

The analysis side reads a whole sharded set at once::

    uv run analysis-cluster out/alt.*.npz --background out/reference.*.npz --delta
"""

from __future__ import annotations

import argparse
from pathlib import Path

from evo.embeddings.cli import (
    _quiet,
    _stderr,
    add_shared_options,
    resolve_settings,
    run_shard,
)
from evo.embeddings.extract import Evo2Embedder
from evo.utils.reference import FastaReference

ALLELES = ("reference", "alt")
"""Both halves of the job, in run order. See *Ordering and sharding* above."""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m evo.embeddings",
        description="Embed the reference allele and every sample's insertion "
                    "allele from an SV VCF, in one pass with one model load.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("vcf", help="SV VCF; per-sample FORMAT ID/RAL/AAL/LN/CO are read")
    p.add_argument("reference", help="indexed reference FASTA")
    p.add_argument("outdir", help="directory to write reference.npz and alt.npz into")
    p.add_argument("--alleles", default="both", choices=("both", *ALLELES),
                   help="which halves to run; 'both' is the point of this command")
    return add_shared_options(p)


def shard_name(allele: str, offset: int = 0, limit: int | None = None) -> str:
    """File name for one allele of one shard.

    A whole-VCF run writes ``alt.npz``. A shard puts its input range in the
    name -- ``alt.2000-4000.npz`` -- because sharding is the documented way to
    survive an ephemeral worker and several shards routinely land in one output
    directory. A fixed name would have shard 1 silently overwrite shard 0, and
    the loss would only show up as a short row count during analysis.
    """
    if offset == 0 and limit is None:
        return f"{allele}.npz"
    end = "end" if limit is None else str(offset + limit)
    return f"{allele}.{offset}-{end}.npz"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = _quiet if args.quiet else _stderr

    layers, segments, pooling, spec = resolve_settings(args)
    alleles = ALLELES if args.alleles == "both" else (args.alleles,)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    log(f"reference: {args.reference}")
    reference = FastaReference(args.reference)
    log(f"layers ({len(layers)}): {', '.join(layers)}")
    log(f"segments ({len(segments)}): {', '.join(segments)}")
    log(f"alleles: {', '.join(alleles)} -> {outdir}/")

    # Loaded here, not inside run_shard, so both halves share one model.
    embedder = None
    if not args.dry_run:
        kernels = " (Triton HC kernels)" if args.use_kernels else ""
        log(f"loading {args.model} on {args.device}{kernels} ...")
        embedder = Evo2Embedder(
            args.model, args.device, use_kernels=args.use_kernels
        )

    written: list[tuple[str, int]] = []
    for allele in alleles:
        out = outdir / shard_name(allele, args.offset, args.limit)
        rows = run_shard(
            str(out), args.vcf, reference, spec,
            layers=layers, segments=segments, pooling=pooling,
            background=allele == "reference",
            max_n_fraction=args.max_n_fraction,
            offset=args.offset, limit=args.limit,
            embedder=embedder, model=args.model, reference_path=args.reference,
            progress=not args.quiet, log=log,
        )
        written.append((out.name, rows))

    verb = "would write" if args.dry_run else "wrote"
    log(f"{verb}: " + ", ".join(f"{name} ({rows} rows)" for name, rows in written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
