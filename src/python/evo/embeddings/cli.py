"""``evo-embed`` -- run Evo 2 over the insertions in an SV VCF.

    evo-embed calls.vcf hg38.fasta out.npz --layers default

The command is deliberately the only place that touches all four modules, so
each of them stays independently testable: :mod:`~evo.embeddings.loci` reads the
VCF, :mod:`~evo.embeddings.windows` cuts the windows,
:mod:`~evo.embeddings.extract` runs the model and
:mod:`~evo.embeddings.store` writes the result.

``--dry-run`` does everything except load Evo 2, which is how you check window
construction, N filtering and the output shape on a laptop before queueing GPU
time.

``--offset``/``--limit`` cut the VCF into shards that each write their own
``.npz``. A full run is long enough that an ephemeral GPU worker can lose it
whole, and this module has no checkpointing, so a shard is the unit of restart::

    evo-embed calls.vcf hg38.fa shard0.npz --offset 0    --limit 2000
    evo-embed calls.vcf hg38.fa shard1.npz --offset 2000 --limit 2000
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Iterator

from evo.embeddings.extract import (
    LAYER_SETS,
    POOLINGS,
    SEGMENT_POOLING,
    extract,
)
from evo.embeddings.loci import InsertionCall, read_insertions
from evo.embeddings.windows import SEGMENTS, WindowSpec, build_window
from evo.utils.reference import FastaReference


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="evo-embed",
        description="Embed SV insertion loci with Evo 2.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("vcf", help="SV VCF; per-sample FORMAT ID/RAL/AAL/LN/CO are read")
    p.add_argument("reference", help="indexed reference FASTA")
    p.add_argument("out", help="output .npz")

    g = p.add_argument_group("window")
    g.add_argument("--flank", type=int, default=WindowSpec().flank,
                   help="reference bases each side of the breakpoint")
    g.add_argument("--junction", type=int, default=WindowSpec().junction,
                   help="bases either side of a breakpoint forming a junction span")
    g.add_argument("--repeat-crop", type=int, default=WindowSpec().repeat_crop,
                   help="cap on inserted bases kept; 0 keeps the whole insertion")
    g.add_argument("--max-n-fraction", type=float, default=0.1,
                   help="skip windows with more N than this; 1 keeps everything")

    g = p.add_argument_group("model")
    g.add_argument("--model", default="evo2_7b_base", help="Evo 2 checkpoint")
    g.add_argument("--device", default="cuda:0")
    g.add_argument("--layers", default="default",
                   help=f"a named set ({', '.join(LAYER_SETS)}) or a comma-separated list")
    g.add_argument("--segments", default=",".join(SEGMENTS),
                   help="comma-separated segment names to pool")
    g.add_argument("--pooling", default="",
                   help="override per segment, e.g. 'repeat=last,left=mean'")

    p.add_argument("--offset", type=int, default=0,
                   help="skip this many insertions before starting")
    p.add_argument("--limit", type=int, help="stop after this many insertions")
    p.add_argument("--dry-run", action="store_true",
                   help="build windows and report, but do not load Evo 2")
    p.add_argument("--quiet", action="store_true")
    return p


def select(
    calls: Iterable[InsertionCall], offset: int = 0, limit: int | None = None
) -> Iterator[InsertionCall]:
    """Yield the calls in the half-open input range ``[offset, offset + limit)``.

    Indexing is over the *input* stream, before the contig and N filters, which
    is what makes a shard a partition: shard *k* covers exactly the same calls
    however many windows shard *k-1* happened to drop. Indexing surviving
    windows instead would make every shard boundary depend on the reference.
    """
    if offset < 0:
        raise SystemExit(f"--offset {offset} must not be negative")
    if limit is not None and limit < 0:
        raise SystemExit(f"--limit {limit} must not be negative")
    stop = None if limit is None else offset + limit
    for i, call in enumerate(calls):
        if i < offset:
            continue
        if stop is not None and i >= stop:
            return
        yield call


def resolve_layers(spec: str) -> list[str]:
    if spec in LAYER_SETS:
        return list(LAYER_SETS[spec])
    layers = [s.strip() for s in spec.split(",") if s.strip()]
    if not layers:
        raise SystemExit(f"--layers {spec!r} names no layers")
    return layers


def resolve_pooling(spec: str) -> dict[str, str]:
    pooling = dict(SEGMENT_POOLING)
    for item in (s.strip() for s in spec.split(",")):
        if not item:
            continue
        name, _, how = item.partition("=")
        if how not in POOLINGS:
            raise SystemExit(f"--pooling {item!r}: expected one of {POOLINGS}")
        if name not in SEGMENTS:
            raise SystemExit(f"--pooling {item!r}: unknown segment {name!r}")
        pooling[name] = how
    return pooling


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a, file=sys.stderr))

    layers = resolve_layers(args.layers)
    segments = [s.strip() for s in args.segments.split(",") if s.strip()]
    unknown = set(segments) - set(SEGMENTS)
    if unknown:
        raise SystemExit(f"--segments: unknown {sorted(unknown)}; have {list(SEGMENTS)}")
    pooling = resolve_pooling(args.pooling)

    spec = WindowSpec(
        flank=args.flank,
        junction=args.junction,
        repeat_crop=args.repeat_crop or None,
    )

    log(f"reference: {args.reference}")
    reference = FastaReference(args.reference)

    calls = select(read_insertions(args.vcf), args.offset, args.limit)
    windows, samples, svids = [], [], []
    skipped_contig = 0
    contigs = set(reference.contigs)
    for call in calls:
        if call.chrom not in contigs:
            skipped_contig += 1
            continue
        windows.append(
            build_window(reference, call.chrom, call.pos, call.insert, spec)
        )
        samples.append(call.sample)
        svids.append(call.svid)

    end = "end" if args.limit is None else str(args.offset + args.limit)
    log(f"shard: calls [{args.offset}, {end})")
    log(f"windows: {len(windows)}  (skipped, contig not in reference: {skipped_contig})")
    if windows:
        lens = [len(w.sequence) for w in windows]
        dirty = sum(w.n_fraction > args.max_n_fraction for w in windows)
        log(f"  length min {min(lens)} max {max(lens)} (spec max {spec.max_length})")
        log(f"  above --max-n-fraction {args.max_n_fraction}: {dirty} (will be skipped)")
    log(f"layers ({len(layers)}): {', '.join(layers)}")
    log(f"segments ({len(segments)}): {', '.join(segments)}")

    if args.dry_run:
        n = sum(w.n_fraction <= args.max_n_fraction for w in windows)
        log(f"\ndry run: would write {n} x {len(layers)} x {len(segments)} x 8192 "
            f"to {args.out}")
        return 0

    from evo.embeddings.extract import Evo2Embedder
    from evo.embeddings.store import save

    log(f"loading {args.model} on {args.device} ...")
    embedder = Evo2Embedder(args.model, args.device)

    keep = {id(w): (s, v) for w, s, v in zip(windows, samples, svids)}
    vectors, kept = extract(
        windows, embedder,
        layers=layers, segments=segments, pooling=pooling,
        max_n_fraction=args.max_n_fraction if args.max_n_fraction < 1 else None,
        progress=not args.quiet,
    )
    kept_samples = [keep[id(w)][0] for w in kept]
    kept_svids = [keep[id(w)][1] for w in kept]

    save(
        args.out, vectors, kept, layers, segments,
        samples=kept_samples, svids=kept_svids,
        attrs={
            "model": args.model,
            "flank": str(spec.flank),
            "junction": str(spec.junction),
            "repeat_crop": str(spec.repeat_crop),
            "pooling": ",".join(f"{k}={v}" for k, v in sorted(pooling.items())),
            "offset": str(args.offset),
            "limit": "" if args.limit is None else str(args.limit),
            "vcf": args.vcf,
            "reference": args.reference,
        },
    )
    log(f"wrote {args.out}: {vectors.shape}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
