"""The command-line surface both steps share: "which view of which run".

``analysis-reduce`` and ``analysis-cluster`` are separate steps that exchange
files and never import each other, but they both begin by answering the same
five questions -- which run, which layer, which segment, which strand, and
against which background. Spelling the flags out twice is how the two drift
into disagreeing about what ``--normalize l2`` means.

Kept out of :mod:`analysis.matrix` so that module stays free of argparse and
usable from a notebook.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from analysis.matrix import (
    NORMALIZATIONS,
    delta,
    design,
    finite_layers,
    load_runs,
    prepare,
    view,
)


def add_view_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Add the flags that select and condition one matrix."""
    parser.add_argument("npz", nargs="+",
                        help="embedding run(s) from evo-embed; several are "
                             "treated as shards of one run and concatenated")

    g = parser.add_argument_group("view")
    g.add_argument("--layer", help="layer to analyse (default: first finite one)")
    g.add_argument("--segment", default="junction_5p",
                   help="segment to analyse")
    g.add_argument("--strand", default="both",
                   choices=("both", "forward", "reverse"),
                   help="which half of concat(forward, reverse_complement)")
    g.add_argument("--normalize", default="l2", choices=NORMALIZATIONS,
                   help="scaling applied before any distance is computed")
    g.add_argument("--allow-nonfinite", action="store_true",
                   help="zero inf/NaN instead of refusing; for inspecting a "
                        "layer that overflowed float16")

    g = parser.add_argument_group("background")
    g.add_argument("--background", nargs="+", metavar="NPZ",
                   help="reference-allele run from `evo-embed --background`; "
                        "with --delta, subtracted per breakpoint")
    g.add_argument("--delta", action="store_true",
                   help="analyse alt minus reference rather than alt, which "
                        "cancels the locus baseline carried by the flanks")

    parser.add_argument("--list", action="store_true",
                        help="print the run's layers, segments and metadata, "
                             "then exit")
    return parser


def resolve_layer(emb, wanted: str | None, segment: str) -> str:
    """The layer to use, defaulting to the first that survived float16."""
    usable = finite_layers(emb, segment)
    if not usable:
        raise SystemExit(
            f"every layer is inf or NaN at segment {segment!r}; the run needs "
            "re-extracting with a wider dtype (see store.save)"
        )
    if wanted is None:
        return usable[0]
    if wanted not in emb.layers:
        raise SystemExit(f"--layer {wanted!r}: not in this run; have {emb.layers}")
    return wanted


def load_view(args: argparse.Namespace, log=print) -> tuple[np.ndarray, pd.DataFrame, str]:
    """Load, select, condition. Returns the matrix, its design frame, and a
    human-readable label naming exactly what was built."""
    emb = load_runs(args.npz)
    if args.segment not in emb.segments:
        raise SystemExit(
            f"--segment {args.segment!r}: not in this run; have {emb.segments}"
        )
    layer = resolve_layer(emb, args.layer, args.segment)
    frame = design(emb)

    if args.delta or args.background:
        if not args.background:
            raise SystemExit("--delta needs --background NPZ ...")
        bg = load_runs(args.background)
        X, mask = delta(emb, bg, layer, args.segment, args.strand, args.normalize)
        frame = frame[mask].reset_index(drop=True)
        missing = int((~mask).sum())
        if missing:
            log(f"dropped {missing} rows with no background window at their breakpoint")
        kind = "alt-ref"
    else:
        X = prepare(
            view(emb, layer, args.segment, args.strand, args.allow_nonfinite),
            args.normalize,
        )
        kind = "alt"

    label = (f"{layer}/{args.segment} [{args.strand}, {args.normalize}, {kind}] "
             f"{X.shape[0]}x{X.shape[1]}")
    log(label)
    return X, frame, label


def describe(args: argparse.Namespace) -> int:
    """``--list``: what is in this run, and what of it is usable."""
    emb = load_runs(args.npz)
    frame = design(emb)
    print(f"windows: {len(emb.vectors)}   loci: {frame['locus'].nunique()}   "
          f"samples: {frame['sample'].nunique()}")
    print(f"segments: {', '.join(emb.segments)}")
    print("layers:")
    for layer in emb.layers:
        ok = [s for s in emb.segments if layer in finite_layers(emb, s)]
        state = "finite" if len(ok) == len(emb.segments) else (
            "NONFINITE (unusable)" if not ok else f"finite only at {', '.join(ok)}"
        )
        print(f"  {layer:20s} {state}")
    print("settings:")
    for key, value in sorted(emb.attrs.items()):
        print(f"  {key:16s} {value}")
    print(f"insert_length: min {frame['insert_length'].min()} "
          f"median {frame['insert_length'].median():.0f} "
          f"max {frame['insert_length'].max()}   "
          f"cropped: {int(frame['cropped'].sum())}")
    return 0


def write_table(frame: pd.DataFrame, path: str, log=print) -> None:
    """TSV, or stdout for ``-``. Every output of both steps goes through here so
    they stay joinable on ``row``."""
    if path == "-":
        frame.to_csv(sys.stdout, sep="\t", index=False, na_rep="NA")
        return
    frame.to_csv(path, sep="\t", index=False, na_rep="NA")
    log(f"wrote {path}  ({len(frame)} rows)")
