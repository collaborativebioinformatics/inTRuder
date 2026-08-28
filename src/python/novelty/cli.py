"""Command line for screening SV-insertion tandem repeats against a reference.

``uv sync`` installs this as the ``novelty`` command, runnable from anywhere in
the repo; ``python -m novelty`` from ``src/python`` is the same program without
installing anything. Paths below are relative to the repo root.

    # what can we screen against?
    uv run novelty platforms

    # one locus
    uv run novelty query --chrom chr1 --pos 10772 --motif GC

    # the whole sv_trfcaller.py table, against both catalogues
    uv run novelty --platform ucsc,trexplorer annotate \\
        data/sv_output/survivor_multi_sample_vcf/first_500_INS.trf.tsv \\
        data/sv_output/survivor_multi_sample_vcf/first_500_INS.novelty.tsv

    # how sensitive is the answer to the thresholds?
    uv run novelty --platform ucsc,trexplorer sweep \\
        data/sv_output/survivor_multi_sample_vcf/first_500_INS.trf.tsv \\
        data/sv_output/survivor_multi_sample_vcf/first_500_INS.sweep.tsv \\
        --window 0,1,10 --max-motif-edits 0,1,2 --min-purity none,0.8

Every platform gets its own block of output columns (``ucsc_novelty``,
``trexplorer_novelty``, ..., each with a ``_match`` column naming the rule that
accepted the motif), and the leading ``novelty`` column combines them: a locus is
only novel if no catalogue knows it.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from trcore.coords import to_external, to_internal
from trcore.motifs import (
    MAX_FUZZY_MOTIF,
    STR_MAX_MOTIF,
    MotifEquivalence,
    MotifTolerance,
    canonical_motif,
)

from .catalog import STATUSES, UNSCREENED, RepeatCatalog, RepeatFilter
from .insertions import PASS, Check, add_insertion_purity, filter_reasons
from .platforms import (
    CACHE_ENV,
    PLATFORMS,
    READERS,
    canonical_motifs,
    ensure_table,
    get_platform,
)
from .search import (
    OBJECTIVES,
    SAMPLERS,
    agreement,
    balanced_accuracy,
    parse_axis,
    read_truth,
    run_study,
)

# known < novel_motif < novel_locus < unscreened: the most conservative verdict
# wins when several catalogues disagree, so a locus is novel only if none of them
# has it. `unscreened` ranks last because it is an absence of coverage rather
# than a verdict -- any catalogue with an actual opinion outranks it, and the
# combined verdict is only `unscreened` when every catalogue was silent.
_PRECEDENCE = {status: rank for rank, status in enumerate(STATUSES)}
_BY_RANK = dict(enumerate(STATUSES))


# --------------------------------------------------------------------------- #
# hyperparameters
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Hyper:
    """One tunable knob, declared once and wired into `query`, `annotate`, `sweep`."""

    name: str
    kind: Callable[[str], object]
    default: object
    metavar: str
    help: str
    affects_screen: bool     # does changing it require re-screening the table?

    @property
    def flag(self) -> str:
        return "--" + self.name.replace("_", "-")


# Defaults are the ones worth shipping: `window=10` because breakpoints are
# rarely placed exactly on the annotated repeat edge, exact motif matching, and
# no row filtering at all -- screen everything, decide what to keep afterwards.
HYPERPARAMS: tuple[Hyper, ...] = (
    Hyper("window", int, 10, "BP",
          "how far a reference repeat may sit from the query coordinate and still "
          "count as the same locus (0 = must overlap it)", True),
    Hyper("max_motif_edits", int, 0, "N",
          "accept a reference motif within N edits of the query motif as a match "
          "(0 = exact). A flat budget at every length, so raising it to 1 also "
          "lets CAG match CAT", True),
    Hyper("max_motif_edit_fraction", float, None, "FRAC",
          f"also accept a reference motif within FRAC x its length, for motifs "
          f"longer than {STR_MAX_MOTIF}bp only. The VNTR knob: two catalogues "
          f"rarely agree on a long consensus but do agree to within a few "
          f"percent of it", True),
    Hyper("min_subrepeat_motif", int, None, "BP",
          "also accept a reference motif that the query motif tiles (ACC against "
          "a reference consensus of ACCATC), when the tiling motif is at least "
          "this long. Shares the edit budgets above, so it does nothing unless "
          "one of them is set", True),
    Hyper("max_fuzzy_motif", int, MAX_FUZZY_MOTIF, "BP",
          "longest motif near-miss matching is attempted on; above this, motifs "
          "must match exactly", True),
    Hyper("min_reference_identity", float, None, "PCT",
          "ignore reference repeats below this percent identity (UCSC perMatch, "
          "0-100); catalogues without the column are unaffected", True),
    Hyper("min_reference_copy_num", float, None, "N",
          "ignore reference repeats with fewer than this many copies", True),
    Hyper("min_reference_length", int, None, "BP",
          "ignore reference repeats shorter than this", True),
    Hyper("min_purity", float, None, "FRAC",
          "flag rows whose own repeat is less pure than this (TRF identity, 0-1)",
          False),
    Hyper("min_insertion_purity", float, None, "FRAC",
          "flag rows whose whole insertion is less than this fraction tandem "
          "repeat (0-1)", False),
    Hyper("min_motif_length", int, None, "BP", "flag rows with a shorter motif", False),
    Hyper("max_motif_length", int, None, "BP", "flag rows with a longer motif", False),
    Hyper("min_rep_length", int, None, "BP",
          "flag rows whose repeat covers fewer bases of the insertion", False),
    Hyper("min_rep_units", float, None, "N",
          "flag rows with fewer copies of the motif in the insertion", False),
)

SCREEN_HYPERPARAMS = tuple(h for h in HYPERPARAMS if h.affects_screen)
FILTER_HYPERPARAMS = tuple(h for h in HYPERPARAMS if not h.affects_screen)

# Trials differing only in row filters reuse a screen; this bounds how many of
# those per-row status tables are held at once. Optuna visits a grid in shuffled
# order, so the cache has to span more than the neighbouring trials -- they are
# stored as categoricals (one byte per row per platform), which makes that cheap.
_SCREEN_CACHE = 64

# Row filters: hyperparameter -> (input column, filter tag, which bound it sets).
_FILTER_COLUMNS = {
    "min_purity": ("purity", "low_purity", "minimum"),
    "min_insertion_purity": ("insertion_purity", "low_insertion_purity", "minimum"),
    "min_motif_length": ("motif_length", "short_motif", "minimum"),
    "max_motif_length": ("motif_length", "long_motif", "maximum"),
    "min_rep_length": ("rep_length", "short_repeat", "minimum"),
    "min_rep_units": ("rep_units", "few_units", "minimum"),
}


def _optional(kind: Callable[[str], object]) -> Callable[[str], object]:
    """`none` clears a threshold, so a sweep axis can include "off"."""

    def parse(value: str):
        return None if str(value).strip().lower() in ("none", "off", "") else kind(value)

    return parse


def _list_of(kind: Callable[[str], object]) -> Callable[[str], list]:
    """Comma-separated values for one sweep axis."""

    def parse(value: str) -> list:
        return [_optional(kind)(part) for part in value.split(",")]

    return parse


def _add_hyperparams(parser: argparse.ArgumentParser, *, sweep: bool = False,
                     only: tuple[Hyper, ...] = HYPERPARAMS) -> None:
    group = parser.add_argument_group(
        "hyperparameters",
        "comma-separated lists; the sweep runs their cartesian product, and "
        "`none` turns a threshold off" if sweep
        else "`none` turns a threshold off; see the `sweep` command to search them")
    for hyper in only:
        if sweep:
            group.add_argument(hyper.flag, default=str(hyper.default),
                               metavar=f"{hyper.metavar}[,...|lo:hi[:step]]",
                               help=f"{hyper.help} (default: {hyper.default})")
        else:
            group.add_argument(hyper.flag, type=_optional(hyper.kind),
                               default=hyper.default, metavar=hyper.metavar,
                               help=f"{hyper.help} (default: %(default)s)")


def _params(args: argparse.Namespace) -> dict:
    return {hyper.name: getattr(args, hyper.name) for hyper in HYPERPARAMS}


def _equivalence(args: argparse.Namespace) -> MotifEquivalence:
    """Build the motif-equivalence policy from the flags, warning once if inert.

    Cached on the namespace: it is needed by catalogue loading, by the query
    canonicalisation and by the report, and the warning should appear once.
    """
    cached = getattr(args, "_equivalence", None)
    if cached is not None:
        return cached
    if args.reverse_complement_bp is not None and not args.reverse_complement:
        print("[novelty] --reverse-complement-bp does nothing without "
              "--reverse-complement; motifs and their reverse complements are "
              "being kept apart at every length", file=sys.stderr)
    equivalence = MotifEquivalence(
        circular=args.circular,
        reverse_complement=args.reverse_complement,
        reverse_complement_bp=args.reverse_complement_bp,
    )
    args._equivalence = equivalence
    return equivalence


def _repeat_filter(params: dict) -> RepeatFilter:
    return RepeatFilter(
        min_identity=params.get("min_reference_identity"),
        min_copy_num=params.get("min_reference_copy_num"),
        min_length=params.get("min_reference_length"),
    )


def _tolerance(params: dict) -> MotifTolerance:
    """How far off a reference motif may be, from the screening hyperparameters."""
    return MotifTolerance(
        max_edits=params.get("max_motif_edits") or 0,
        max_edit_fraction=params.get("max_motif_edit_fraction"),
        min_subrepeat_motif=params.get("min_subrepeat_motif"),
        max_fuzzy_motif=params.get("max_fuzzy_motif") or MAX_FUZZY_MOTIF,
    )


def _warn_inert_tolerance(tolerance: MotifTolerance) -> None:
    """Say so when --min-subrepeat-motif was asked for but has no budget to spend."""
    if (tolerance.min_subrepeat_motif is not None
            and not tolerance.max_edits and not tolerance.max_edit_fraction):
        print("[novelty] --min-subrepeat-motif has no edit budget to spend: an "
              "exact tiling is already handled by period reduction, so this does "
              "nothing on its own. Pair it with --max-motif-edits or "
              "--max-motif-edit-fraction", file=sys.stderr)


# --------------------------------------------------------------------------- #
# catalogue loading
# --------------------------------------------------------------------------- #

def _platform_list(value: str) -> list[str]:
    names = [name.strip() for name in value.split(",") if name.strip()]
    unknown = [name for name in names if name not in PLATFORMS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown platform(s) {', '.join(unknown)}; expected "
            f"{', '.join(PLATFORMS)}"
        )
    if not names:
        raise argparse.ArgumentTypeError("--platform needs at least one name")
    if all(PLATFORMS[name].annotation_only for name in names):
        raise argparse.ArgumentTypeError(
            f"{', '.join(names)} is annotation-only and cannot decide novelty on "
            f"its own; add a genome-wide catalogue such as "
            f"{', '.join(n for n, p in PLATFORMS.items() if not p.annotation_only)}"
        )
    return names


def _repeat_paths(specs: list[str] | None, platforms: list[str]) -> dict[str, Path]:
    """Parse ``--repeats [PLATFORM=]PATH``; a bare path needs a single platform."""
    paths: dict[str, Path] = {}
    for spec in specs or []:
        name, sep, raw = spec.partition("=")
        if not sep:
            if len(platforms) != 1:
                raise SystemExit(
                    f"error: --repeats {spec!r} is ambiguous with several platforms; "
                    f"write it as PLATFORM=PATH"
                )
            name, raw = platforms[0], spec
        if name not in platforms:
            raise SystemExit(f"error: --repeats names platform {name!r}, "
                             f"which is not in --platform")
        paths[name] = Path(raw)
    return paths


def _screening_platforms(names: list[str]) -> list[str]:
    """The platforms whose verdict counts towards novelty, annotation ones aside."""
    return [name for name in names if not get_platform(name).annotation_only]


def _load_catalogs(args: argparse.Namespace) -> dict[str, RepeatCatalog]:
    overrides = _repeat_paths(args.repeats, args.platform)
    catalogs: dict[str, RepeatCatalog] = {}
    for name in args.platform:
        override = overrides.get(name)
        platform = get_platform(name)
        table = ensure_table(name, args.db, override, cache_dir=args.cache_dir,
                             download=override is None and not args.no_download)
        # A catalogue kept in the repo is small by construction, so building its
        # index is faster than reading a cache of it anyway.
        bundled = table == platform.bundled_path(args.db)
        catalogs[name] = RepeatCatalog.from_file(
            table, platform=name, fmt=args.format, equivalence=_equivalence(args),
            cache=not args.no_cache and not bundled, verbose=not bundled,
        )
    return catalogs


def _warn_inapplicable(catalogs: dict[str, RepeatCatalog], params: dict) -> None:
    """Say once when a reference threshold has no column in some catalogue."""
    repeat_filter = _repeat_filter(params)
    for name, catalog in catalogs.items():
        missing = repeat_filter.inapplicable(catalog.annotations)
        if missing:
            print(f"[novelty] {name}: no column for {', '.join(missing)}; those "
                  f"thresholds do not apply to it", file=sys.stderr)


def _warn_uncovered(catalogs: dict[str, RepeatCatalog], chroms) -> None:
    """Name the query contigs a catalogue has no rows for, once per catalogue.

    Those rows come back ``unscreened`` rather than ``novel_locus``, and saying
    which contigs they were is the difference between a reader trusting the
    number and wondering about it.
    """
    unique = sorted({str(c) for c in pd.Series(chroms, dtype=object).dropna()})
    for name, catalog in catalogs.items():
        missing = [c for c in unique if not catalog.covers(c)]
        if missing:
            shown = ", ".join(missing[:5]) + ("..." if len(missing) > 5 else "")
            print(f"[novelty] {name}: no repeats on {len(missing)} of "
                  f"{len(unique)} query contig(s) ({shown}); those rows are "
                  f"'{UNSCREENED}', not novel", file=sys.stderr)


def _combine(statuses: pd.DataFrame) -> pd.Series:
    """One verdict per row across platforms, taking the most conservative."""
    ranks = statuses.apply(lambda column: column.map(_PRECEDENCE))
    return ranks.min(axis=1).map(_BY_RANK)


# --------------------------------------------------------------------------- #
# the screening core, shared by `annotate` and `sweep`
# --------------------------------------------------------------------------- #

def _prepare(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Read the input table and compute everything no hyperparameter changes."""
    frame = pd.read_csv(args.input, sep="\t", dtype={args.chrom_col: "string",
                                                     args.motif_col: "string"})
    for column in (args.chrom_col, args.pos_col, args.motif_col):
        if column not in frame.columns:
            raise KeyError(f"column {column!r} not in {args.input} header: "
                           f"{list(frame.columns)}")

    points = to_internal(pd.to_numeric(frame[args.pos_col], errors="raise"),
                         args.coord_base)
    base = pd.DataFrame(index=frame.index)
    base["canonical_motif"] = canonical_motifs(frame[args.motif_col],
                                               _equivalence(args))
    if args.insertion_purity:
        purity = add_insertion_purity(
            frame, keys=args.insertion_key, start_col=args.rep_start_col,
            end_col=args.rep_end_col, size_col=args.insert_size_col)
        for column in ("insertion_repeat_bases", "insertion_purity"):
            base[column] = purity[column]
    return frame, points, base


def _screen(frame: pd.DataFrame, points: pd.Series,
            catalogs: dict[str, RepeatCatalog], params: dict,
            args: argparse.Namespace) -> tuple[list[pd.DataFrame], pd.DataFrame]:
    """Screen every row against every catalogue at one set of screen parameters."""
    repeat_filter = _repeat_filter(params)
    tolerance = _tolerance(params)
    blocks: list[pd.DataFrame] = []
    statuses = pd.DataFrame(index=frame.index)
    for name, catalog in catalogs.items():
        block = catalog.screen_frame(
            frame[args.chrom_col], points, frame[args.motif_col],
            window=params["window"], tolerance=tolerance,
            repeat_filter=repeat_filter, prefix=f"{name}_",
        )
        block[f"{name}_start"], block[f"{name}_end"] = to_external(
            block[f"{name}_start"], block[f"{name}_end"], args.coord_base)
        # An annotation catalogue still gets its block of columns, but it covers
        # a handful of loci by design, so letting it vote would call almost every
        # row novel on the strength of a catalogue that was never a genome-wide
        # claim in the first place.
        if not get_platform(name).annotation_only:
            statuses[name] = block[f"{name}_novelty"]
        blocks.append(block)
    return blocks, statuses


def _checks(params: dict, purity_col: str) -> list[Check]:
    """Turn the row-filter hyperparameters into column thresholds."""
    checks: list[Check] = []
    for name, (column, tag, bound) in _FILTER_COLUMNS.items():
        value = params.get(name)
        if value is None:
            continue
        if name == "min_purity":
            column = purity_col
        checks.append(Check(column, tag, **{bound: value}))
    return checks


def _locus_status(frame: pd.DataFrame, novelty: pd.Series,
                  locus_cols: list[str]) -> pd.Series:
    ranks = novelty.map(_PRECEDENCE)
    return ranks.groupby([frame[c] for c in locus_cols], sort=False).min().map(_BY_RANK)


def _locus_table(frame: pd.DataFrame, extra: pd.DataFrame, statuses: pd.DataFrame,
                 locus_cols: list[str]) -> pd.DataFrame:
    """One row per surviving locus: the combined verdict and each platform's.

    Loci, not rows, are the unit both the summaries and the search objectives
    work in -- rows are locus x sample x TRF call, so a recurrent locus would
    otherwise vote dozens of times.
    """
    passing = extra["filter"] == PASS
    kept = frame.loc[passing]
    table = pd.DataFrame(
        {"novelty": _locus_status(kept, extra.loc[passing, "novelty"], locus_cols)})
    for name in statuses.columns:
        table[name] = _locus_status(kept, statuses.loc[passing, name], locus_cols)
    return table


def _metrics(params: dict, frame: pd.DataFrame, extra: pd.DataFrame,
             loci: pd.DataFrame) -> dict:
    """One row of the sweep table: the parameters and what they produced."""
    passing = extra["filter"] == PASS
    row: dict = dict(params)
    row["n_rows"] = len(frame)
    row["n_rows_pass"] = int(passing.sum())

    counts = extra.loc[passing, "novelty"].value_counts()
    for status in STATUSES:
        row[f"rows_{status}"] = int(counts.get(status, 0))

    locus_counts = loci["novelty"].value_counts()
    row["n_loci"] = len(loci)
    for status in STATUSES:
        row[f"loci_{status}"] = int(locus_counts.get(status, 0))
    row["frac_loci_novel"] = (round(1 - locus_counts.get("known", 0) / len(loci), 4)
                              if len(loci) else None)

    for name in loci.columns.drop("novelty"):
        counts = loci[name].value_counts()
        for status in STATUSES:
            row[f"{name}_loci_{status}"] = int(counts.get(status, 0))
    return row


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #

def _print_counts(label: str, statuses: pd.Series) -> None:
    counts = statuses.value_counts()
    total = int(counts.sum()) or 1
    print(f"[novelty] {label} (n={total:,})", file=sys.stderr)
    for status in STATUSES:
        n = int(counts.get(status, 0))
        print(f"[novelty]   {status:<12} {n:>8,}  ({100 * n / total:5.1f}%)",
              file=sys.stderr)


def _report(frame: pd.DataFrame, novelty: pd.Series, locus_cols: list[str]) -> None:
    """Per-row and per-locus summaries.

    Rows are locus x sample x TRF call, so one recurrent locus can contribute
    dozens of them; per-row percentages on their own say more about how often a
    locus recurs than about how much of the genome is novel.
    """
    _print_counts("per row", novelty)
    if all(column in frame.columns for column in locus_cols):
        _print_counts(f"per locus ({'+'.join(locus_cols)})",
                      _locus_status(frame, novelty, locus_cols))


def _write_metrics(path: str, rows: list[dict]) -> None:
    """Write (or append to) the metrics table, so external sweeps can accumulate."""
    table = pd.DataFrame(rows)
    target = Path(path)
    if target.exists():
        existing = pd.read_csv(target, sep="\t")
        table = pd.concat([existing, table], ignore_index=True)
    table.to_csv(target, sep="\t", index=False, na_rep="NA")


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #

def _cmd_platforms(args: argparse.Namespace) -> int:
    print("platforms (--platform):")
    for platform in PLATFORMS.values():
        assemblies = ", ".join(platform.assemblies) if platform.assemblies else "any"
        role = "annotation only" if platform.annotation_only else "screening"
        print(f"  {platform.name:<12} {platform.description}")
        print(f"  {'':<12} assemblies: {assemblies}   role: {role}")
        if platform.url:
            print(f"  {'':<12} {platform.url}")
    print("\nfile formats (--format), auto-detected by default:")
    for name in sorted(READERS):
        print(f"  {name}")
    print("\nmotif tolerance -- how far off a reference motif may be:")
    print(f"  {'--max-motif-edits N':<26} default 0   flat budget at every length")
    print(f"  {'--max-motif-edit-fraction F':<26} default off proportional budget, "
          f">{STR_MAX_MOTIF}bp motifs only")
    print(f"  {'--min-subrepeat-motif BP':<26} default off accept a motif that "
          f"tiles the other")
    print("  the last two need each other's company: a tiling with no edit "
          "budget is\n  already handled by period reduction")
    print("\nmotif equivalence -- what makes two motifs the same repeat:")
    print(f"  {'period reduction':<26} always on   CAGCAG == CAG")
    print(f"  {'--circular':<26} default on  CAG == AGC == GCA (rotation)")
    print(f"  {'--reverse-complement':<26} default OFF CAG == CTG (opposite strand)")
    print(f"  {'--reverse-complement-bp BP':<26} default off apply the above only to "
          f"motifs >= BP")
    print("  none of these is fuzzy matching; --max-motif-edits does that, "
          "and defaults to 0")

    print("\nhyperparameters (see `annotate --help`, search them with `sweep`):")
    for hyper in HYPERPARAMS:
        scope = "screening" if hyper.affects_screen else "row filter"
        print(f"  {hyper.flag:<26} {scope:<10} default {hyper.default}")
    return 0


def _cmd_query(args: argparse.Namespace) -> int:
    catalogs = _load_catalogs(args)
    params = {hyper.name: getattr(args, hyper.name, hyper.default)
              for hyper in HYPERPARAMS}
    _warn_inapplicable(catalogs, params)
    repeat_filter = _repeat_filter(params)
    tolerance = _tolerance(params)
    _warn_inert_tolerance(tolerance)
    point = to_internal(args.pos, args.coord_base)

    equivalence = _equivalence(args)
    canonical = canonical_motif(args.motif, equivalence)
    print(f"{args.chrom}:{args.pos} ({args.coord_base}-based)  "
          f"motif={args.motif.strip().upper()}  canonical={canonical}")
    print(f"  same repeat if it differs by: {equivalence.describe()}")
    print(f"  motif tolerance             : {tolerance.describe()}")

    verdicts = {}
    for name, catalog in catalogs.items():
        verdict = catalog.screen(args.chrom, point, args.motif,
                                 window=params["window"], tolerance=tolerance,
                                 repeat_filter=repeat_filter)
        verdicts[name] = verdict
        print(f"  {name}")
        print(f"    status      : {verdict.status}"
              + ("" if catalog.covers(args.chrom)
                 else f"  ({name} has no repeats on {verdict.chrom} at all)"))
        print(f"    nearby (+/-{params['window']}bp): {verdict.n_nearby} "
              f"reference repeat(s)")
        if verdict.best is not None:
            repeat = verdict.best.repeat
            start, end = to_external(repeat.start, repeat.end, args.coord_base)
            label = verdict.best.match if verdict.best.motif_matches else "nearest"
            print(f"    best {label:<9}: {repeat.chrom}:{start}-{end}  "
                  f"motif={repeat.motif} (canonical={repeat.canonical}, "
                  f"{verdict.best.motif_edits} edit(s), "
                  f"{verdict.best.distance}bp away)")
            if repeat.annotations:
                print("    " + " " * 12 + " ".join(
                    f"{k}={v}" for k, v in repeat.annotations.items()))

    screening = {name: verdict for name, verdict in verdicts.items()
                 if not get_platform(name).annotation_only}
    if len(screening) > 1:
        combined = min(screening.values(), key=lambda v: _PRECEDENCE[v.status])
        print(f"  combined      : {combined.status}")
    return 0


def _cmd_annotate(args: argparse.Namespace) -> int:
    params = _params(args)
    if params["min_insertion_purity"] is not None and not args.insertion_purity:
        print("error: --min-insertion-purity needs the purity columns; drop "
              "--no-insertion-purity", file=sys.stderr)
        return 2
    try:
        frame, points, base = _prepare(args)
        checks = _checks(params, args.purity_col)
        _validate_checks(checks, frame, base, args.input)
    except KeyError as exc:
        print(f"error: {exc.args[0]}", file=sys.stderr)
        return 2

    catalogs = _load_catalogs(args)
    _warn_inapplicable(catalogs, params)
    _warn_inert_tolerance(_tolerance(params))
    _warn_uncovered(catalogs, frame[args.chrom_col])
    blocks, statuses = _screen(frame, points, catalogs, params, args)

    extra = base.copy()
    extra.insert(0, "novelty", _combine(statuses))
    extra["filter"] = filter_reasons(pd.concat([frame, extra], axis=1), checks)

    out = pd.concat([frame, extra, *blocks], axis=1)
    kept = out.loc[out["filter"] == PASS] if args.drop_filtered else out
    kept.to_csv(args.output, sep="\t", index=False, na_rep="NA")

    print(f"[novelty] {args.output}: {len(kept):,} of {len(out):,} row(s), "
          f"platforms: {', '.join(catalogs)}", file=sys.stderr)
    passing = out.loc[out["filter"] == PASS]
    if len(passing) < len(out):
        print(f"[novelty] {len(out) - len(passing):,} row(s) failed a filter: "
              + ", ".join(f"{tag}={n:,}" for tag, n in
                          out.loc[out["filter"] != PASS, "filter"]
                          .value_counts().items()), file=sys.stderr)
    locus_cols = [args.chrom_col, args.pos_col]
    _report(passing, passing["novelty"], locus_cols)
    if args.metrics:
        loci = _locus_table(frame, extra, statuses, locus_cols)
        _write_metrics(args.metrics, [_metrics(params, frame, extra, loci)])
        print(f"[novelty] metrics -> {args.metrics}", file=sys.stderr)
    return 0


def _cmd_sweep(args: argparse.Namespace) -> int:
    """Search the hyperparameter space with Optuna, one metrics row per trial."""
    try:
        frame, points, base = _prepare(args)
        axes = [parse_axis(hyper.name, hyper.kind, getattr(args, hyper.name),
                           optional=_optional)
                for hyper in HYPERPARAMS]
        truth = (read_truth(args.truth, [args.chrom_col, args.pos_col], args.truth_col)
                 if args.truth else None)
        objective = _resolve_objective(args, truth)
    except (KeyError, ValueError) as exc:
        print(f"error: {exc.args[0] if exc.args else exc}", file=sys.stderr)
        return 2

    catalogs = _load_catalogs(args)
    _warn_uncovered(catalogs, frame[args.chrom_col])
    locus_cols = [args.chrom_col, args.pos_col]
    screen_names = [hyper.name for hyper in SCREEN_HYPERPARAMS]
    # Row filters do not change the screen, so trials that differ only in them
    # reuse it. Only the small per-row status table is cached, never the full
    # annotation blocks, so this stays cheap on a large input.
    cache: dict[tuple, pd.DataFrame] = {}
    warned = False

    def evaluate(params: dict) -> tuple[dict, float]:
        nonlocal warned
        if not warned:
            _warn_inapplicable(catalogs, params)
            warned = True
        key = tuple(params[name] for name in screen_names)
        cached = cache.get(key)
        if cached is None:
            _, statuses = _screen(frame, points, catalogs, params, args)
            if len(cache) >= _SCREEN_CACHE:
                cache.pop(next(iter(cache)))
            cache[key] = statuses.astype("category")
        else:
            statuses = cached.astype(object)

        extra = base.copy()
        extra.insert(0, "novelty", _combine(statuses))
        extra["filter"] = filter_reasons(pd.concat([frame, extra], axis=1),
                                         _checks(params, args.purity_col))
        loci = _locus_table(frame, extra, statuses, locus_cols)
        row = _metrics(params, frame, extra, loci)
        score = objective(loci)
        row["objective"] = args.objective
        row["score"] = score
        return row, score

    try:
        rows = run_study(axes, evaluate, sampler=args.sampler, trials=args.trials,
                         seed=args.seed, storage=args.storage,
                         study_name=args.study_name, direction=args.direction)
    except (KeyError, ValueError) as exc:
        print(f"error: {exc.args[0] if exc.args else exc}", file=sys.stderr)
        return 2
    if not rows:
        print("error: no trial completed", file=sys.stderr)
        return 1

    _write_metrics(args.output, rows)
    table = pd.DataFrame(rows)
    novel = table["n_loci"] - table["loci_known"]
    print(f"[novelty] {args.output}: {len(rows):,} trial(s)", file=sys.stderr)
    print(f"[novelty] loci called novel across the search: {int(novel.min()):,}"
          f"..{int(novel.max()):,} (of {int(table['n_loci'].max()):,} loci at the "
          f"loosest row filter)", file=sys.stderr)
    if args.objective != "none":
        best = table.loc[table["score"].idxmax() if args.direction == "maximize"
                         else table["score"].idxmin()]
        tuned = {h.name: _scalar(best[h.name]) for h in HYPERPARAMS
                 if best[h.name] != h.default and pd.notna(best[h.name])}
        print(f"[novelty] best {args.objective} = {best['score']:.4f} at "
              f"{tuned or 'the defaults'}", file=sys.stderr)
    return 0


def _scalar(value):
    """numpy scalars out of pandas do not repr like the Python values."""
    return value.item() if hasattr(value, "item") else value


def _resolve_objective(args: argparse.Namespace,
                       truth: pd.Series | None) -> Callable[[pd.DataFrame], float]:
    """Pick the objective, defaulting to what the run can actually compute."""
    if args.objective is None:
        args.objective = ("truth" if truth is not None
                          else "agreement" if len(args.platform) > 1 else "none")
    if args.objective == "truth":
        if truth is None:
            raise ValueError("--objective truth needs --truth PATH")
        return lambda loci: balanced_accuracy(loci, truth)
    if args.objective == "agreement":
        platforms = list(args.platform)
        if len(platforms) < 2:
            raise ValueError("--objective agreement needs at least two --platform "
                             "entries; use --objective truth or none")
        return lambda loci: agreement(loci, platforms)
    if args.sampler == "tpe":
        raise ValueError("--sampler tpe optimises, so it needs an objective; pass "
                         "--objective agreement or truth")
    return lambda loci: 0.0


def _validate_checks(checks: list[Check], frame: pd.DataFrame, base: pd.DataFrame,
                     source: str) -> None:
    available = set(frame.columns) | set(base.columns)
    for check in checks:
        if check.column not in available:
            raise KeyError(f"cannot filter on {check.column!r}: column not in {source}")


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #

def _add_table_args(parser: argparse.ArgumentParser) -> None:
    """Options describing the sv_trfcaller.py table, shared by annotate and sweep."""
    parser.add_argument("input", help="TSV from sv_trfcaller.py")
    parser.add_argument("--chrom-col", default="chrom")
    parser.add_argument("--pos-col", default="ins_coord",
                        help="reference coordinate of the insertion "
                             "(default: %(default)s)")
    parser.add_argument("--motif-col", default="motif")
    parser.add_argument("--purity-col", default="purity",
                        help="per-repeat TRF identity column (default: %(default)s)")
    parser.add_argument("--no-insertion-purity", dest="insertion_purity",
                        action="store_false",
                        help="skip the per-insertion purity columns")
    parser.add_argument("--insertion-key", metavar="COLS",
                        default=["chrom", "ins_coord", "SVID", "sample"],
                        type=lambda v: [c.strip() for c in v.split(",") if c.strip()],
                        help="comma-separated columns identifying one insertion "
                             "(default: chrom,ins_coord,SVID,sample)")
    parser.add_argument("--rep-start-col", default="rep_start")
    parser.add_argument("--rep-end-col", default="rep_end")
    parser.add_argument("--insert-size-col", default="insert_size")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="novelty",
        description="Screen SV-insertion tandem repeats against reference TR catalogues.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n\n", 1)[-1],
    )
    parser.add_argument("--platform", type=_platform_list, default=["ucsc"],
                        help="comma-separated reference catalogue(s) to screen "
                             "against (default: ucsc; see the `platforms` command)")
    parser.add_argument("--db", default="hg38",
                        help="assembly to screen against (default: %(default)s)")
    parser.add_argument("--repeats", metavar="[PLATFORM=]PATH", action="append",
                        help="local catalogue file, instead of the downloaded one; "
                             "repeatable, one per platform")
    parser.add_argument("--format", default="auto", choices=("auto", *sorted(READERS)),
                        help="catalogue file layout (default: %(default)s)")
    parser.add_argument("--cache-dir", metavar="PATH", default=None,
                        help=f"where downloaded catalogues live (default: the "
                             f"repo's data/reference, or ${CACHE_ENV})")
    parser.add_argument("--no-download", action="store_true",
                        help="fail instead of fetching a missing catalogue")
    parser.add_argument("--no-cache", action="store_true",
                        help="rebuild the index instead of using its .idx.npz cache")
    parser.add_argument("--coord-base", type=int, choices=(0, 1), default=1,
                        help="coordinate convention of the INPUT position and of the "
                             "reported start/end; VCF POS is 1-based "
                             "(default: %(default)s)")
    equivalence = parser.add_argument_group(
        "motif equivalence",
        "what makes two motif strings the same repeat. Reducing a motif to its "
        "primitive unit (CAGCAG -> CAG) is always done. These are catalogue-level "
        "settings -- they decide how the index is keyed, so they rebuild it and "
        "cannot be swept. None of them is fuzzy matching: see --max-motif-edits "
        "for that, which is off by default")
    equivalence.add_argument(
        "--circular", action=argparse.BooleanOptionalAction,
        default=True,
        help="treat every rotation of a motif as the same repeat, so CAG, AGC "
             "and GCA agree. TRF picks the starting phase arbitrarily on both "
             "sides of the comparison (default: enabled; --no-circular to "
             "require the same phase)")
    equivalence.add_argument(
        "--reverse-complement", action="store_true",
        help="also treat a motif's reverse complement as the same repeat, so CAG "
             "and CTG agree. Off by default: it also merges the homopolymers A "
             "and T. (GC and CG are rotations, not a strand pair -- they agree "
             "either way)")
    equivalence.add_argument(
        "--reverse-complement-bp", type=int, default=None, metavar="BP",
        help="only apply --reverse-complement to motifs at least this long, "
             "keeping the strands apart for short motifs where an RC match is "
             "most likely coincidental. Does nothing unless "
             "--reverse-complement is given (default: every length)")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("platforms", help="list the catalogues, formats and hyperparameters"
                   ).set_defaults(func=_cmd_platforms)

    query = sub.add_parser("query", help="screen a single coordinate + motif")
    query.add_argument("--chrom", required=True)
    query.add_argument("--pos", required=True, type=int)
    query.add_argument("--motif", required=True)
    _add_hyperparams(query, only=SCREEN_HYPERPARAMS)
    query.set_defaults(func=_cmd_query)

    annotate = sub.add_parser("annotate",
                              help="screen every row of an sv_trfcaller.py TSV")
    _add_table_args(annotate)
    annotate.add_argument("output", help="annotated TSV to write")
    annotate.add_argument("--drop-filtered", action="store_true",
                          help="write only rows that pass every filter")
    annotate.add_argument("--metrics", metavar="PATH",
                          help="also append a one-row summary of this run, in the "
                               "same layout the `sweep` command writes")
    _add_hyperparams(annotate)
    annotate.set_defaults(func=_cmd_annotate)

    sweep = sub.add_parser("sweep",
                           help="run the grid of hyperparameters and tabulate what "
                                "each combination produces")
    _add_table_args(sweep)
    sweep.add_argument("output", help="metrics TSV to write, one row per trial")
    sweep.add_argument("--sampler", choices=SAMPLERS, default="grid",
                       help="grid enumerates every combination; tpe and random "
                            "optimise the objective (default: %(default)s)")
    sweep.add_argument("--trials", type=int, default=None, metavar="N",
                       help="how many trials to run (default: the whole grid, "
                            "or 50 when sampling)")
    sweep.add_argument("--objective", choices=OBJECTIVES, default=None,
                       help="what to optimise: `agreement` scores how far the "
                            "platforms independently flag the same loci, `truth` "
                            "scores against --truth, `none` just enumerates "
                            "(default: agreement when several platforms, else none)")
    sweep.add_argument("--direction", choices=("maximize", "minimize"),
                       default="maximize", help="(default: %(default)s)")
    sweep.add_argument("--truth", metavar="PATH",
                       help="TSV of labelled loci: the chrom/pos columns plus a "
                            "novelty/status column")
    sweep.add_argument("--truth-col", default=None,
                       help="label column in --truth (default: novelty/status/label)")
    sweep.add_argument("--seed", type=int, default=None,
                       help="sampler seed, for a reproducible search")
    sweep.add_argument("--storage", metavar="URL",
                       help="Optuna storage, e.g. sqlite:///study.db, to keep the "
                            "trials and resume or browse them later")
    sweep.add_argument("--study-name", default=None,
                       help="study name within --storage")
    _add_hyperparams(sweep, sweep=True)
    sweep.set_defaults(func=_cmd_sweep)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
