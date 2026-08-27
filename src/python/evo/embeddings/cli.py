"""``evo-embed`` -- run Evo 2 over one allele of an SV VCF and write one ``.npz``.

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

``--background`` embeds the **reference allele** at the same breakpoints instead
of the insertions. It is the control the analysis half needs and costs about a
third of the alt run, since one window covers every sample called at a
breakpoint::

    evo-embed calls.vcf hg38.fa alt.npz
    evo-embed calls.vcf hg38.fa ref.npz --background

Running those two as separate commands loads Evo 2 twice and makes it possible
to ship an alt run with no control -- which is what happened on the first full
attempt. :mod:`evo.embeddings.__main__` (``python -m evo.embeddings``) is the
same work as one command into one directory, and is what a GPU job should call.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence

from evo.embeddings.extract import (
    D_MODEL,
    LAYER_SETS,
    POOLINGS,
    SEGMENT_POOLING,
    Embedder,
    Evo2Embedder,
    extract,
)
from evo.embeddings.loci import InsertionCall, read_insertions
from evo.embeddings.store import save
from evo.embeddings.windows import SEGMENTS, WindowSpec, build_window
from evo.utils.reference import FastaReference, Reference


def _quiet(*args: object) -> None:
    """The ``--quiet`` logger."""


def _stderr(*args: object) -> None:
    """The default logger. stderr, so stdout stays free for piped output."""
    print(*args, file=sys.stderr)


def add_shared_options(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Add the window, model and shard flags that every entry point takes.

    Declared once rather than copied because an alt run and its reference-allele
    control are only comparable if they were cut and pooled *identically*: a
    ``--flank`` that drifted between the two parsers would produce two files
    that still load, still join on ``(chrom, pos)``, and quietly mean different
    things. Sharing the declarations makes that drift impossible.
    """
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
    # Vortex's Triton kernels cover the Hyena convolutions -- 27 of the 32
    # layers, and the bandwidth-bound part of the pass. Opt-in on both sides:
    # evo2 defaults it off and tells you to validate outputs, because vortex
    # falls back silently when a kernel is unavailable.
    g.add_argument("--use-kernels", action="store_true",
                   help="Vortex Triton kernels for the Hyena convolutions; "
                        "faster, but validate vectors before trusting a run")

    g = p.add_argument_group("shard")
    g.add_argument("--offset", type=int, default=0,
                   help="skip this many insertions before starting")
    g.add_argument("--limit", type=int, help="stop after this many insertions")

    p.add_argument("--dry-run", action="store_true",
                   help="build windows and report, but do not load Evo 2")
    p.add_argument("--quiet", action="store_true")
    return p


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="evo-embed",
        description="Embed one allele of an SV VCF's insertion loci with Evo 2.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("vcf", help="SV VCF; per-sample FORMAT ID/RAL/AAL/LN/CO are read")
    p.add_argument("reference", help="indexed reference FASTA")
    p.add_argument("out", help="output .npz")
    p.add_argument("--background", action="store_true",
                   help="embed the REFERENCE allele at each breakpoint instead "
                        "of the insertion: same flanks, no insert. One window "
                        "per distinct breakpoint, not per call")
    return add_shared_options(p)


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


def build_windows(
    calls: Iterable[InsertionCall],
    reference,
    spec: WindowSpec,
    background: bool = False,
) -> tuple[list, list[str], list[str], int]:
    """Windows for a stream of calls, plus their sample and svid labels.

    ``background=True`` builds the **reference allele** at each breakpoint --
    identical flanks, ``insert=""`` -- which is the control the whole comparison
    rests on: subtract it and what is left is what the insertion did, with the
    locus cancelled out.

    It emits one window per *distinct* ``(chrom, pos)`` rather than one per
    call, because the reference allele does not depend on which sample was
    called there. That is not just an optimisation: on the benchmark slice, 100
    calls sit at 31 distinct breakpoints, so the background costs a third of the
    alt run rather than the same again. Sample and svid come back empty for
    those rows, which is what marks them as background downstream.

    Breakpoints are deduplicated, *not* rounded to the record ``POS``: 59% of
    per-sample calls sit at a non-zero offset from it (median 34 bp), and a
    junction span is only 128 bp wide, so collapsing them would misplace the
    control by half its width.

    Deduplication is *within the shard*, so a breakpoint spanning an ``--offset``
    boundary is embedded twice. Harmless -- the two windows are identical and
    the analysis side joins on the first match -- but it means the background
    shards are not quite a partition the way the alt shards are.
    """
    contigs = set(reference.contigs)
    windows, samples, svids = [], [], []
    skipped_contig = 0
    seen: set[tuple[str, int]] = set()

    for call in calls:
        if call.chrom not in contigs:
            skipped_contig += 1
            continue
        if background:
            key = (call.chrom, call.pos)
            if key in seen:
                continue
            seen.add(key)
            windows.append(build_window(reference, call.chrom, call.pos, "", spec))
            samples.append("")
            svids.append("")
        else:
            windows.append(
                build_window(reference, call.chrom, call.pos, call.insert, spec)
            )
            samples.append(call.sample)
            svids.append(call.svid)
    return windows, samples, svids, skipped_contig


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


def resolve_segments(spec: str) -> list[str]:
    segments = [s.strip() for s in spec.split(",") if s.strip()]
    unknown = set(segments) - set(SEGMENTS)
    if unknown:
        raise SystemExit(f"--segments: unknown {sorted(unknown)}; have {list(SEGMENTS)}")
    if not segments:
        raise SystemExit(f"--segments {spec!r} names no segments")
    return segments


def resolve_settings(
    args: argparse.Namespace,
) -> tuple[list[str], list[str], dict[str, str], WindowSpec]:
    """Turn the shared flags into the four things extraction actually needs.

    Shared by both entry points for the same reason :func:`add_shared_options`
    is: declaring the flags once is only half of it, since two parsers could
    still interpret ``--repeat-crop 0`` differently.
    """
    return (
        resolve_layers(args.layers),
        resolve_segments(args.segments),
        resolve_pooling(args.pooling),
        WindowSpec(
            flank=args.flank,
            junction=args.junction,
            repeat_crop=args.repeat_crop or None,
        ),
    )


def run_shard(
    out: str,
    vcf: str,
    reference: Reference,
    spec: WindowSpec,
    *,
    layers: Sequence[str],
    segments: Sequence[str],
    pooling: dict[str, str],
    background: bool = False,
    max_n_fraction: float = 0.1,
    offset: int = 0,
    limit: int | None = None,
    embedder: Embedder | None = None,
    model: str = "",
    reference_path: str = "",
    progress: bool = False,
    log: Callable[..., None] = _quiet,
) -> int:
    """Embed one allele of one shard and write it to ``out``. Returns rows written.

    Both entry points funnel through here, and that is what keeps a two-allele
    run honest: the ``alt.npz`` and ``reference.npz`` it produces went through
    the same window spec, the same layer list and the same pooling because there
    is only one piece of code that can apply them.

    ``embedder=None`` is the dry run -- windows are built and reported, Evo 2 is
    never loaded and nothing is written; the return value is then the number of
    rows that *would* be written. The caller constructs the embedder rather than
    this function, so a two-allele run pays the model load once.
    """
    calls = select(read_insertions(vcf), offset, limit)
    windows, samples, svids, skipped_contig = build_windows(
        calls, reference, spec, background=background
    )

    allele = "reference" if background else "alt"
    end = "end" if limit is None else str(offset + limit)
    log(f"[{allele}] calls [{offset}, {end}): {len(windows)} windows "
        f"(skipped, contig not in reference: {skipped_contig})")
    if background:
        log(f"[{allele}] one window per distinct breakpoint, not per call")
    if windows:
        lens = [len(w.sequence) for w in windows]
        dirty = sum(w.n_fraction > max_n_fraction for w in windows)
        log(f"[{allele}]   length min {min(lens)} max {max(lens)} "
            f"(spec max {spec.max_length})")
        log(f"[{allele}]   above --max-n-fraction {max_n_fraction}: {dirty} (skipped)")

    if embedder is None:
        n = sum(w.n_fraction <= max_n_fraction for w in windows)
        log(f"[{allele}] dry run: would write {n} x {len(layers)} x "
            f"{len(segments)} x {2 * D_MODEL} to {out}")
        return n

    labels = {id(w): (s, v) for w, s, v in zip(windows, samples, svids)}
    vectors, kept = extract(
        windows, embedder,
        layers=layers, segments=segments, pooling=pooling,
        max_n_fraction=max_n_fraction if max_n_fraction < 1 else None,
        progress=progress,
    )

    save(
        out, vectors, kept, list(layers), list(segments),
        samples=[labels[id(w)][0] for w in kept],
        svids=[labels[id(w)][1] for w in kept],
        attrs={
            "model": model,
            "flank": str(spec.flank),
            "junction": str(spec.junction),
            "repeat_crop": str(spec.repeat_crop),
            "pooling": ",".join(f"{k}={v}" for k, v in sorted(pooling.items())),
            "allele": allele,
            "offset": str(offset),
            "limit": "" if limit is None else str(limit),
            "vcf": vcf,
            "reference": reference_path,
        },
    )
    log(f"[{allele}] wrote {out}: {vectors.shape}")
    return len(vectors)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = _quiet if args.quiet else _stderr

    layers, segments, pooling, spec = resolve_settings(args)

    log(f"reference: {args.reference}")
    reference = FastaReference(args.reference)
    log(f"layers ({len(layers)}): {', '.join(layers)}")
    log(f"segments ({len(segments)}): {', '.join(segments)}")

    embedder = None
    if not args.dry_run:
        kernels = " (Triton HC kernels)" if args.use_kernels else ""
        log(f"loading {args.model} on {args.device}{kernels} ...")
        embedder = Evo2Embedder(
            args.model, args.device, use_kernels=args.use_kernels
        )

    run_shard(
        args.out, args.vcf, reference, spec,
        layers=layers, segments=segments, pooling=pooling,
        background=args.background,
        max_n_fraction=args.max_n_fraction,
        offset=args.offset, limit=args.limit,
        embedder=embedder, model=args.model, reference_path=args.reference,
        progress=not args.quiet, log=log,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
