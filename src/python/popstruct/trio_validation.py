#!/usr/bin/env python3
"""Mendelian consistency of TR calls in the GIAB trio.

A tandem repeat called in the child (HG002) should normally be present in at
least one parent (HG003, HG004). Loci found in the child and neither parent are
Mendelian violations: a false positive in the child, a false negative in a
parent, or, rarely, a true de novo event.

Known loci provide the control. Their violation rate is the floor set by
parental dropout and SV-calling inconsistency rather than by novelty, so the
quantity of interest is each novel class's *excess* over that floor.

    python src/python/popstruct/trio_validation.py [INPUT.tsv]
"""
import sys
from pathlib import Path

import pandas as pd
from scipy import stats

DEFAULT = Path("data/sv_output/novelty_filtered/"
               "HG002_03_04_multisample.trf.novelyFilter.tsv")
CHILD, FATHER, MOTHER = "HG002", "HG003", "HG004"
RANK = {"known": 0, "novel_motif": 1, "novel_locus": 2, "unscreened": 3}


def per_locus(path):
    t = pd.read_csv(path, sep="\t", low_memory=False)
    t["s"] = t["sample"].str.split(".").str[0]
    loc = (t.groupby(["chrom", "ins_coord"])
             .agg(members=("s", frozenset),
                  novelty=("novelty", lambda s: min(s, key=lambda v: RANK.get(v, 9))))
             .reset_index())
    for who, tag in [(CHILD, "child"), (FATHER, "father"), (MOTHER, "mother")]:
        loc[tag] = loc.members.apply(lambda m, w=who: w in m)
    return loc


def jeffreys_ci(k, n):
    """Jeffreys interval; behaves sensibly at small n, unlike Wald."""
    lo, hi = stats.beta.ppf([0.025, 0.975], k + 0.5, n - k + 0.5)
    return lo * 100, hi * 100


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    loc = per_locus(path)
    child = loc[loc.child].copy()
    child["violation"] = ~(child.father | child.mother)

    print(f"loci in trio call set : {len(loc):,}")
    print(f"carried by the child  : {len(child):,}")
    print(f"Mendelian violations  : {int(child.violation.sum()):,} "
          f"({child.violation.mean() * 100:.1f}%)\n")

    print(f"{'class':<13}{'n':>7}{'viol':>7}{'rate':>8}{'95% CI':>17}")
    base = None
    for v in ["known", "novel_motif", "novel_locus"]:
        s = child[child.novelty == v]
        if s.empty:
            continue
        k, n = int(s.violation.sum()), len(s)
        lo, hi = jeffreys_ci(k, n)
        print(f"{v:<13}{n:>7,}{k:>7,}{k / n * 100:>7.1f}%   [{lo:5.1f}, {hi:5.1f}]")
        if v == "known":
            base = (k, n)

    print("\nExcess over the known-locus control:")
    for v in ["novel_motif", "novel_locus"]:
        s = child[child.novelty == v]
        if s.empty or base is None:
            continue
        k, n = int(s.violation.sum()), len(s)
        odds, p = stats.fisher_exact([[k, n - k], [base[0], base[1] - base[0]]])
        print(f"  {v:<12} OR = {odds:4.2f}  Fisher p = {p:7.4f}  "
              f"excess = {k / n * 100 - base[0] / base[1] * 100:+5.1f} pts")


if __name__ == "__main__":
    main()
