#!/usr/bin/env python3
import argparse
import csv
import statistics as stats
import sys

REQUIRED_COLUMNS = [
    "chrom", "ins_coord", "SVID", "depth", "insert_size", "sample", "allele",
    "rep_start", "rep_end", "motif", "purity", "motif_length",
    "rep_length", "rep_units",
]

NUMERIC_FIELDS = {
    "depth": lambda x: sum([(int(v)) for v in x.split(",")]) if "," in x else int(x),
    "insert_size": int,
    "rep_start": int,
    "rep_end": int,
    "purity": float,
    "motif_length": int,
    "rep_length": int,
    "rep_units": float,
}


def parse_args():
    p = argparse.ArgumentParser(
        description="Filter insertion+TRF TSV and generate summary stats.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("-i", "--input", required=True, help="Input TSV file")
    p.add_argument("-o", "--output", required=True, help="Filtered output TSV path")
    p.add_argument(
        "-s", "--stats-output", default=None,
        help="Stats TSV output path (default: <output>.stats.tsv)",
    )
    p.add_argument(
        "--exclude-motif-sizes", default="",
        help="Comma-separated motif sizes to DROP, e.g. '1,2,3,10'. "
             "Leave empty to keep all motif sizes.",
    )
    p.add_argument(
        "--keep-motif-sizes", default="",
        help="Comma-separated motif sizes to KEEP exclusively (applied "
             "after --exclude-motif-sizes). Leave empty to disable.",
    )
    p.add_argument(
        "--min-repeat-coverage", type=float, default=0.8,
        help="Minimum fraction of the insertion covered by the repeat "
             "(rep_length / insert_size).",
    )
    p.add_argument(
        "--min-purity", type=float, default=0.7,
        help="Minimum TRF purity (column 'purity', 0-1 scale). "
             "NOTE: no purity default was specified in the request; 0.7 "
             "is a reasonable starting point -- adjust as needed.",
    )
    p.add_argument(
        "--max-insert-size", type=int, default=10000,
        help="Maximum insertion size in bp; insertions longer than this "
             "are removed.",
    )
    p.add_argument(
        "--min-depth", type=int, default=30,
        help="Minimum number of supporting reads ('depth'). Default: 30.",
    )
    return p.parse_args()


def parse_int_list(s):
    if not s:
        return set()
    out = set()
    for tok in s.split(","):
        tok = tok.strip()
        if tok:
            out.add(int(tok))
    return out


def load_rows(path):
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            sys.exit(
                f"ERROR: input file is missing required column(s): {missing}\n"
                f"Found columns: {reader.fieldnames}"
            )
        rows = []
        n_bad = 0
        for raw in reader:
            row = dict(raw)
            ok = True
            for field, caster in NUMERIC_FIELDS.items():
                try:
                    row[field] = caster(row[field])
                except (TypeError, ValueError):
                    ok = False
                    break
            if not ok:
                n_bad += 1
                continue
            rows.append(row)
    if n_bad:
        print(f"WARNING: skipped {n_bad} row(s) with non-numeric values in "
              f"expected numeric columns.", file=sys.stderr)
    return rows, reader.fieldnames


def add_repeat_coverage(rows):
    for r in rows:
        ins_len = r["insert_size"]
        r["repeat_coverage"] = (r["rep_length"] / ins_len) if ins_len > 0 else 0.0
    return rows


def run_filters(rows, args):
    """Apply each filter in sequence, logging a funnel of counts."""
    exclude_sizes = parse_int_list(args.exclude_motif_sizes)
    keep_sizes = parse_int_list(args.keep_motif_sizes)

    funnel = []
    current = rows
    funnel.append({"step": "input", "rows_in": len(current),
                    "rows_removed": 0, "rows_remaining": len(current)})

    def apply_step(name, predicate):
        nonlocal current
        before = len(current)
        kept = [r for r in current if predicate(r)]
        removed = before - len(kept)
        funnel.append({
            "step": name, "rows_in": before,
            "rows_removed": removed, "rows_remaining": len(kept),
        })
        current = kept

    if exclude_sizes:
        apply_step(
            f"exclude_motif_sizes({sorted(exclude_sizes)})",
            lambda r: r["motif_length"] not in exclude_sizes,
        )

    if keep_sizes:
        apply_step(
            f"keep_motif_sizes_only({sorted(keep_sizes)})",
            lambda r: r["motif_length"] in keep_sizes,
        )

    apply_step(
        f"min_repeat_coverage(>={args.min_repeat_coverage})",
        lambda r: r["repeat_coverage"] >= args.min_repeat_coverage,
    )

    apply_step(
        f"min_purity(>={args.min_purity})",
        lambda r: r["purity"] >= args.min_purity,
    )

    apply_step(
        f"max_insert_size(<={args.max_insert_size})",
        lambda r: r["insert_size"] <= args.max_insert_size,
    )

    apply_step(
        f"min_depth(>={args.min_depth})",
        lambda r: r["depth"] >= args.min_depth,
    )

    return current, funnel


def insertion_key(r):
    return (r["chrom"], r["ins_coord"], r["SVID"], r["sample"])


def write_filtered_tsv(rows, fieldnames, path):
    out_fields = list(fieldnames) + ["repeat_coverage"]
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=out_fields, delimiter="\t")
        writer.writeheader()
        for r in rows:
            row_out = {k: r.get(k, "") for k in out_fields}
            if isinstance(row_out["repeat_coverage"], float):
                row_out["repeat_coverage"] = f"{row_out['repeat_coverage']:.4f}"
            writer.writerow(row_out)


def summarize_by_motif_length(rows):
    groups = {}
    for r in rows:
        groups.setdefault(r["motif_length"], []).append(r)

    summary = []
    for motif_len in sorted(groups):
        grp = groups[motif_len]
        purities = [r["purity"] for r in grp]
        coverages = [r["repeat_coverage"] for r in grp]
        ins_sizes = [r["insert_size"] for r in grp]
        uniq_ins = {insertion_key(r) for r in grp}
        uniq_samples = {r["sample"] for r in grp}
        summary.append({
            "motif_length": motif_len,
            "n_trf_hits": len(grp),
            "n_unique_insertions": len(uniq_ins),
            "n_unique_samples": len(uniq_samples),
            "mean_purity": round(stats.mean(purities), 4),
            "median_purity": round(stats.median(purities), 4),
            "mean_repeat_coverage": round(stats.mean(coverages), 4),
            "median_repeat_coverage": round(stats.median(coverages), 4),
            "mean_insert_size": round(stats.mean(ins_sizes), 1),
            "median_insert_size": round(stats.median(ins_sizes), 1),
        })
    return summary


def write_stats(funnel, motif_summary, rows_in, rows_out, path):
    uniq_ins_in = len({insertion_key(r) for r in rows_in})
    uniq_ins_out = len({insertion_key(r) for r in rows_out})

    with open(path, "w", newline="") as fh:
        fh.write("## Filtering funnel\n")
        writer = csv.DictWriter(
            fh, fieldnames=["step", "rows_in", "rows_removed", "rows_remaining"],
            delimiter="\t",
        )
        writer.writeheader()
        for row in funnel:
            writer.writerow(row)

        fh.write("\n## Unique insertion counts (chrom+ins_coord+SVID+sample)\n")
        fh.write(f"unique_insertions_input\t{uniq_ins_in}\n")
        fh.write(f"unique_insertions_output\t{uniq_ins_out}\n")

        fh.write("\n## Summary by motif_length (final filtered set)\n")
        if motif_summary:
            writer = csv.DictWriter(
                fh, fieldnames=list(motif_summary[0].keys()), delimiter="\t"
            )
            writer.writeheader()
            for row in motif_summary:
                writer.writerow(row)
        else:
            fh.write("(no rows remaining after filtering)\n")


def main():
    args = parse_args()
    rows, fieldnames = load_rows(args.input)
    rows = add_repeat_coverage(rows)

    filtered, funnel = run_filters(rows, args)

    write_filtered_tsv(filtered, fieldnames, args.output)

    stats_path = args.stats_output or (args.output + ".stats.tsv")
    motif_summary = summarize_by_motif_length(filtered)
    write_stats(funnel, motif_summary, rows, filtered, stats_path)

    print(f"Input rows:    {len(rows)}")
    print(f"Output rows:   {len(filtered)}")
    print(f"Filtered TSV:  {args.output}")
    print(f"Stats TSV:     {stats_path}")


if __name__ == "__main__":
    main()
