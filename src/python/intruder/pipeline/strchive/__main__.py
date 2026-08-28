#! /usr/bin/env python3
"""Command line entry point for the STRchive comparison step.

    # cache the pinned catalog (optional; annotate/query do it on demand)
    python -m intruder.pipeline.strchive fetch

    # screen one candidate
    python -m intruder.pipeline.strchive query --chrom chr1 --pos 94418430 --motif CCG --rep-units 120

    # annotate a whole table from the upstream filtering step
    python -m intruder.pipeline.strchive annotate filtered.tsv annotated.tsv --window 500

Run from ``src/python`` (or with it on ``PYTHONPATH``).
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

from .catalog import BUILDS, STRCHIVE_VERSION, Catalog, fetch
from .compare import OUTPUT_COLUMNS, Query, as_row, compare

# Column names as emitted by sv_trfcaller.py, overridable per run so this step
# does not care what the upstream filter chooses to call things.
DEFAULTS = {
    "chrom": "chrom",
    "pos": "ins_coord",
    "motif": "motif",
    "gene": "gene",
    "rep-units": "rep_units",
    "label": "SVID",
}

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _number(value: str | None) -> float | None:
    """First number in a cell, tolerating the ``[138]`` form the caller emits."""
    if value is None:
        return None
    found = _NUMBER.search(str(value))
    return float(found.group()) if found else None


def _add_catalog_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--catalog", type=Path, default=None,
                        help="path to STRchive-loci.json (default: download and cache)")
    parser.add_argument("--strchive-version", default=STRCHIVE_VERSION,
                        help=f"STRchive release tag (default: {STRCHIVE_VERSION})")
    parser.add_argument("--cache-dir", type=Path, default=None,
                        help="where to cache the downloaded catalog "
                             "(default: data/reference/strchive)")
    parser.add_argument("--build", default="hg38", choices=sorted(BUILDS),
                        help="reference build the query coordinates are in (default: hg38)")


def _add_match_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--window", type=int, default=0,
                        help="bp of slack around a disease locus (default: 0, overlap only)")
    parser.add_argument("--max-motif-edits", type=int, default=0,
                        help="accept motifs within this edit distance (default: 0, exact)")
    parser.add_argument("--stranded", action="store_true",
                        help="do not fold motifs onto their reverse complement")
    parser.add_argument("--coord-base", type=int, default=1, choices=(0, 1),
                        help="coordinate base of the input (default: 1, VCF style)")


def _load(args: argparse.Namespace) -> Catalog:
    return Catalog.load(args.catalog, build=args.build, version=args.strchive_version,
                        cache_dir=args.cache_dir, verbose=True)


def cmd_fetch(args: argparse.Namespace) -> int:
    path = fetch(version=args.strchive_version, cache_dir=args.cache_dir,
                 force=args.force, verbose=True)
    catalog = Catalog.from_file(path, build=args.build, version=args.strchive_version)
    print(f"{path}\n{len(catalog)} loci ({args.build}), STRchive {args.strchive_version}")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    catalog = _load(args)
    query = Query.from_point(args.chrom, args.pos, args.motif, coord_base=args.coord_base,
                             gene=args.gene, rep_units=args.rep_units)
    match = compare(query, catalog, window=args.window,
                    max_motif_edits=args.max_motif_edits, stranded=args.stranded)

    print(f"{query.chrom}:{args.pos} {query.motif}  ->  {match.status}")
    if match.locus is None:
        print(f"  no STRchive disease locus within {args.window} bp")
        return 0

    locus = match.locus
    print(f"  locus       {locus.id}  {locus.chrom}:{locus.start}-{locus.end} "
          f"({match.distance} bp away, {match.n_nearby} nearby)")
    print(f"  gene        {locus.gene}"
          + ("" if match.gene_agrees is None
             else f"  (input said {query.gene!r}: "
                  f"{'agrees' if match.gene_agrees else 'DISAGREES'})"))
    print(f"  disease     {locus.disease} [{','.join(locus.inheritance) or '?'}]")
    print(f"  motif       {match.motif_class}"
          + (f" via {match.matched_motif} ({match.motif_edits} edits)"
             if match.matched_motif else " -- not catalogued at this locus"))
    print(f"  reference   {locus.ref_copies} copies, pathogenic motif in ref: {locus.novel}")
    if match.est_copies is not None:
        print(f"  estimate    {locus.ref_copies:g} ref + {query.rep_units:g} inserted "
              f"= {match.est_copies:g} copies -> {match.allele_class}")
    else:
        print("  estimate    unavailable (need --rep-units and a locus with ref_copies)")
    print(f"  ranges      benign {locus.benign_min}-{locus.benign_max}, "
          f"intermediate {locus.intermediate_min}-{locus.intermediate_max}, "
          f"pathogenic {locus.pathogenic_min}-{locus.pathogenic_max}")
    return 0


def cmd_annotate(args: argparse.Namespace) -> int:
    catalog = _load(args)
    columns = {key: getattr(args, f"col_{key.replace('-', '_')}") for key in DEFAULTS}

    with open(args.input, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise SystemExit(f"{args.input}: empty or headerless table")
        missing = [columns[k] for k in ("chrom", "pos", "motif")
                   if columns[k] not in reader.fieldnames]
        if missing:
            raise SystemExit(
                f"{args.input}: required column(s) {missing} not found in "
                f"{list(reader.fieldnames)} -- override with --col-chrom/--col-pos/--col-motif"
            )
        rows = list(reader)
        fieldnames = list(reader.fieldnames)

    # Re-annotating an already-annotated table should replace, not duplicate.
    fieldnames = [name for name in fieldnames if name not in OUTPUT_COLUMNS]
    fieldnames += list(OUTPUT_COLUMNS)

    counts: Counter[str] = Counter()
    with open(args.output, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            pos = _number(row.get(columns["pos"]))
            if pos is None:
                raise SystemExit(f"{args.input}: non-numeric {columns['pos']}={row.get(columns['pos'])!r}")
            query = Query.from_point(
                row[columns["chrom"]], int(pos), row[columns["motif"]],
                coord_base=args.coord_base,
                gene=row.get(columns["gene"]) or None,
                rep_units=_number(row.get(columns["rep-units"])),
                label=row.get(columns["label"]) or "",
            )
            match = compare(query, catalog, window=args.window,
                            max_motif_edits=args.max_motif_edits, stranded=args.stranded)
            counts[match.status] += 1
            row.update(as_row(match, catalog))
            writer.writerow(row)

    total = sum(counts.values())
    print(f"[strchive] {total:,} rows -> {args.output}", file=sys.stderr)
    for status, n in counts.most_common():
        print(f"[strchive]   {status:24} {n:>7,}  ({n / total:.2%})", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m intruder.pipeline.strchive", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="download and cache the STRchive catalog")
    _add_catalog_args(p_fetch)
    p_fetch.add_argument("--force", action="store_true", help="re-download even if cached")
    p_fetch.set_defaults(func=cmd_fetch, catalog=None)

    p_query = sub.add_parser("query", help="screen a single candidate repeat")
    _add_catalog_args(p_query)
    _add_match_args(p_query)
    p_query.add_argument("--chrom", required=True)
    p_query.add_argument("--pos", type=int, required=True, help="insertion point")
    p_query.add_argument("--motif", required=True)
    p_query.add_argument("--gene", default=None, help="gene from upstream annotation")
    p_query.add_argument("--rep-units", type=float, default=None,
                         help="motif copies carried by the insertion")
    p_query.set_defaults(func=cmd_query)

    p_ann = sub.add_parser("annotate", help="annotate a TSV of candidate repeats")
    _add_catalog_args(p_ann)
    _add_match_args(p_ann)
    p_ann.add_argument("input", type=Path)
    p_ann.add_argument("output", type=Path)
    for key, default in DEFAULTS.items():
        p_ann.add_argument(f"--col-{key}", default=default,
                           help=f"input column holding the {key} (default: {default})")
    p_ann.set_defaults(func=cmd_annotate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
