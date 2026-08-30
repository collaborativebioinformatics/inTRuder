#!/usr/bin/env python3
"""Convert Tandem Repeats Finder .dat output to a BED4 catalogue.

TRF .dat data lines are:
    start end period copies consensusSize %match %indel score A C G T entropy consensus aligned
Coordinates are 1-based inclusive; BED is 0-based half-open, so start-1 is used.

    uv run python -m intruder.pipeline.catalog.dat2bed OUT.bed dat/*.dat

``scripts/catalog/build_hg38_trf.sh`` runs this as its last step.
"""
import sys
from pathlib import Path


def convert(dat_paths, out_path):
    rows, skipped = [], 0
    for p in dat_paths:
        chrom = None
        with open(p) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("Sequence:"):
                    chrom = line.split(":", 1)[1].strip().split()[0]
                    continue
                if not line or not line[0].isdigit():
                    continue
                f = line.split()
                if len(f) < 14:
                    skipped += 1
                    continue
                try:
                    start, end = int(f[0]), int(f[1])
                except ValueError:
                    skipped += 1
                    continue
                motif = f[13]
                if chrom is None:
                    chrom = Path(p).name.split(".")[0]
                rows.append((chrom, start - 1, end, motif))
    rows.sort(key=lambda r: (r[0], r[1]))
    with open(out_path, "w") as o:
        for chrom, s, e, m in rows:
            o.write(f"{chrom}\t{s}\t{e}\t{m}\n")
    return len(rows), skipped


if __name__ == "__main__":
    out = sys.argv[1]
    n, skipped = convert(sys.argv[2:], out)
    print(f"{n:,} intervals -> {out}" + (f"  ({skipped} malformed lines skipped)" if skipped else ""))
