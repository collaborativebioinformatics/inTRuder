#!/usr/bin/env python3
"""Cut an SV VCF down to the loci a novelty screen called novel.

    python src/python/filter/subset_vcf_by_novelty.py \
        first_500_INS.vcf first_500_INS.novelty.filtered.tsv novel_INS.vcf

The Evo 2 extraction is priced per window and the whole callset does not fit in
a hackathon's GPU budget, so the question "which loci are worth embedding?" has
to be answered *before* the model is loaded. This is that step, and it is a
separate program on purpose: `novelty annotate` owns the catalogues and the
verdict, `evo.embeddings` owns the windows and the model, and neither has to
import the other. VCF in, VCF out.

Selection is by **(chrom, ins_coord) against (CHROM, POS)**, which is the only
key that actually joins. Two traps, both measured on `first_500_INS`, and both
of which produce a plausible wrong VCF rather than an error:

  * **The table's `SVID` is the per-sample Sniffles ID**, taken from FORMAT, not
    the record's ID column. Only 160 of 208 novel SVIDs appear in that column at
    all, so selecting on it silently drops a quarter of the novel loci.
  * **The VCF's ID column is not unique.** 500 records carry just 227 distinct
    IDs -- a SURVIVOR merge reuses the first sample's ID -- so an ID match also
    pulls in unrelated loci that happen to share a string. Both errors at once
    turned 73 novel loci into 360 kept records.

`(chrom, ins_coord)` matched a VCF `(CHROM, POS)` for 105 of 105 loci. A
coordinate can legitimately name more than one record (24 do here); those are
the same locus, so all of them are kept.

A record is kept when ANY of its rows is novel. The screen is per (locus,
sample, TRF call), so one record can be called novel in one sample and known in
another; keeping it means the embedding run sees every sample at that locus,
which is what makes the samples comparable to each other and to the reference
allele. Dropping the known samples instead would leave a locus whose only
embedded alleles are the unusual ones.
"""

from __future__ import annotations

import argparse
import csv
import sys

#: Verdicts `novelty annotate` can emit. `known` is the only one that is not
#: novel; the other two differ in whether the *locus* or only its *motif* is
#: absent from the catalogues.
NOVEL = ("novel_motif", "novel_locus")


def novel_loci(
    table: str,
    verdicts: tuple[str, ...] = NOVEL,
    require_pass: bool = True,
) -> set[tuple[str, str]]:
    """``(chrom, ins_coord)`` of every locus with a row whose verdict is novel.

    ``require_pass`` honours the ``filter`` column that the purity filters write,
    and is ignored when the table has no such column -- an unfiltered
    `novelty.tsv` has none, and silently keeping nothing would look exactly like
    a table with no novel rows in it.
    """
    with open(table, newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        if reader.fieldnames is None:
            raise SystemExit(f"{table}: empty table")
        for column in ("chrom", "ins_coord", "novelty"):
            if column not in reader.fieldnames:
                raise SystemExit(
                    f"{table}: no {column!r} column; is this a novelty table? "
                    f"got {reader.fieldnames[:8]}"
                )
        has_filter = "filter" in reader.fieldnames
        keep = set()
        for row in reader:
            if require_pass and has_filter and row["filter"] != "PASS":
                continue
            if row["novelty"] in verdicts:
                keep.add((row["chrom"], row["ins_coord"]))
    return keep


def subset(vcf: str, out: str, keep: set[tuple[str, str]]) -> tuple[int, int]:
    """Write ``out`` with the header and only the records at a locus in ``keep``.

    Returns ``(records kept, records seen, loci matched)``.

    Header lines are copied verbatim -- including every `##FORMAT` -- because
    `evo.embeddings.loci` reads per-sample ID/RAL/AAL/LN/CO out of them, and a
    subset that dropped them would parse as a VCF with no calls in it.
    """
    kept = total = 0
    seen: set[tuple[str, str]] = set()
    with open(vcf) as src, open(out, "w") as dst:
        for line in src:
            if line.startswith("#"):
                dst.write(line)
                continue
            total += 1
            chrom, pos, _ = line.split("\t", 2)
            if (chrom, pos) in keep:
                dst.write(line)
                seen.add((chrom, pos))
                kept += 1
    return kept, total, len(seen)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("vcf", help="SV VCF to subset")
    p.add_argument("table", help="novelty table from `novelty annotate`")
    p.add_argument("out", help="output VCF")
    p.add_argument("--novelty", default=",".join(NOVEL),
                   help="comma-separated verdicts that count as novel")
    p.add_argument("--keep-filtered", action="store_true",
                   help="also use rows the purity filters did not pass "
                        "(ignored if the table has no 'filter' column)")
    args = p.parse_args(argv)

    verdicts = tuple(v.strip() for v in args.novelty.split(",") if v.strip())
    unknown = set(verdicts) - {*NOVEL, "known"}
    if unknown:
        raise SystemExit(f"--novelty: unknown verdict(s) {sorted(unknown)}")

    keep = novel_loci(args.table, verdicts, require_pass=not args.keep_filtered)
    if not keep:
        raise SystemExit(
            f"{args.table}: no rows matched {list(verdicts)}"
            + ("" if args.keep_filtered else " among PASS rows (--keep-filtered?)")
        )

    kept, total, matched = subset(args.vcf, args.out, keep)
    print(f"novel loci in {args.table}: {len(keep)}", file=sys.stderr)
    print(f"records kept: {kept} of {total} -> {args.out}", file=sys.stderr)
    # A locus in the table with no record in the VCF means the two files came
    # from different runs. Left unsaid it surfaces much later, as an embedding
    # matrix that is short by an amount nobody can account for.
    missing = len(keep) - matched
    if missing:
        print(f"WARNING: {missing} novel locus/loci are absent from {args.vcf}; "
              f"are the table and the VCF from the same run?", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
