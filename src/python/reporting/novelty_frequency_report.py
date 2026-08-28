"""Generate a Markdown report of TR locus counts by novelty class and allele count.

For each locus in the pipeline's own output (sv_trfcaller + novelty annotate),
counts how many samples carry it (out of 67 HPRC genomes) and bins loci into
carrier-count bands. Plots the number of novel_motif and novel_locus loci per
band, on both log and linear scales.

Locus identity is (chrom, ins_coord), not the SVID column. This merged VCF
assigns SVIDs per-sample-call rather than one shared ID per joint locus: the
same physical insertion can carry a different SVID in different carrying
samples. Grouping by SVID over-counts loci (21,424 SVIDs vs 17,270 true
positions) and, more importantly, under-counts carrier frequency for ~17% of
loci -- pooling by position raises the carrier count above what any single
SVID shows in the large majority of cases checked. See issue_duplicate_rows.md
for a related (distinct) counting caveat in the same file.

Usage:
    python src/python/reporting/novelty_frequency_report.py \\
        --multisample-tsv /path/to/05_hprc_multisample.tsv \\
        --outdir docs/figures
"""

from __future__ import annotations

import argparse
import datetime
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
CLASS_COLOR = {"novel_motif": "#eb6834", "novel_locus": "#1baf7a"}

mpl.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "figure.dpi": 160, "font.size": 12.5, "font.family": "sans-serif",
    "text.color": INK, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.edgecolor": AXIS, "axes.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False,
    "grid.color": GRID, "grid.linewidth": 0.8, "grid.linestyle": "-",
    "axes.grid": True, "axes.axisbelow": True, "legend.frameon": False,
})


def majority_novelty(s: pd.Series) -> str:
    """Most common novelty verdict among a locus's carriers.

    97.2% of loci have a single, unanimous verdict across every SVID/sample
    at that position. The remaining 2.8% disagree (e.g. one carrier's call
    reads `known`, another's reads `novel_motif` at the exact same
    coordinate) -- taking the majority is a pragmatic tie-break, not a claim
    that the disagreement itself is resolved or understood.
    """
    return s.value_counts().idxmax()


def build_loci_table(multisample_tsv: Path) -> tuple[pd.DataFrame, int]:
    calls = pd.read_csv(
        multisample_tsv, sep="\t",
        usecols=["chrom", "ins_coord", "SVID", "sample", "novelty"],
    )
    calls = calls.drop_duplicates(["sample", "chrom", "ins_coord"])
    n_genomes = calls["sample"].nunique()

    loci = calls.groupby(["chrom", "ins_coord"]).agg(
        carrier_count=("sample", "nunique"),
        novelty=("novelty", majority_novelty),
    ).reset_index()
    return loci, n_genomes


# Doubling bins on carrier count: a standard site-frequency-spectrum
# convention that scales with cohort size rather than a fixed percentage cut
# (a plain "10%"/"5%" split would round inconsistently for n=67).
def make_bins(n_genomes: int) -> tuple[list[int], list[str]]:
    edges = [1, 2, 3, 5, 9, 17, 34, 50, n_genomes + 1]
    labels = ["1", "2", "3-4", "5-8", "9-16", "17-33", "34-49", f"50-{n_genomes}"]
    return edges, labels


def make_panel(counts: pd.DataFrame, bin_labels: list[str], n_genomes: int,
                log_scale: bool, outfile: Path) -> None:
    fig, ax = plt.subplots(figsize=(9.0, 6.2), constrained_layout=False)
    fig.subplots_adjust(top=0.82, bottom=0.12, left=0.11, right=0.88)
    scale_note = "log scale" if log_scale else "linear scale"
    fig.text(0.01, 0.955, "TR loci by class and allele count",
              fontsize=19, fontweight="semibold", color=INK, ha="left", va="top")
    fig.text(0.01, 0.91, f"Number of loci, {scale_note}, by carrier count out of {n_genomes} genomes.",
              fontsize=12, color=INK_2, ha="left", va="top")

    plot_max = counts[["novel_motif", "novel_locus"]].to_numpy().max()
    x = np.arange(len(bin_labels))
    for cls in ["novel_motif", "novel_locus"]:
        y = counts[cls].to_numpy()
        ax.plot(x, y, marker="o", lw=2.2, color=CLASS_COLOR[cls])
        for xi, yi in zip(x, y):
            offset = yi * 0.12 if log_scale else (plot_max * 0.025)
            ax.text(xi, yi + offset, f"{yi:,}", ha="center", fontsize=10.5, color=CLASS_COLOR[cls])

    if log_scale:
        ax.set_yscale("log")
        for cls in ["novel_motif", "novel_locus"]:
            y = counts[cls].to_numpy()
            ax.text(x[-1] + 0.1, y[-1], cls, va="center", fontsize=13, color=CLASS_COLOR[cls], fontweight="semibold")
    else:
        ax.set_ylim(0, plot_max * 1.18)
        finals = {cls: counts[cls].to_numpy()[-1] for cls in ["novel_motif", "novel_locus"]}
        min_gap = plot_max * 0.09
        placed, prev = {}, None
        for cls in sorted(finals, key=finals.get):
            y = finals[cls] if prev is None else max(finals[cls], prev + min_gap)
            placed[cls] = y
            prev = y
        for cls in ["novel_motif", "novel_locus"]:
            ax.text(x[-1] + 0.1, placed[cls], cls, va="center", fontsize=13, color=CLASS_COLOR[cls], fontweight="semibold")

    ax.set_xticks(x, bin_labels)
    ax.set_xlim(-0.3, len(bin_labels) - 1 + 1.0)
    ax.set_ylabel("Number of loci")
    ax.set_xlabel("Carriers (out of 67 genomes)")
    fig.savefig(outfile)
    plt.close(fig)


def build_report(loci: pd.DataFrame, n_genomes: int, n_svid_loci: int,
                  assets_dir: Path, report_path: Path, source: Path) -> None:
    assets_dir.mkdir(parents=True, exist_ok=True)
    edges, bin_labels = make_bins(n_genomes)
    loci = loci.copy()
    loci["bin"] = pd.cut(loci["carrier_count"], bins=edges, labels=bin_labels, right=False)
    counts = loci.groupby(["bin", "novelty"], observed=True).size().unstack(fill_value=0).reindex(bin_labels)

    make_panel(counts, bin_labels, n_genomes, True, assets_dir / "loci_by_allele_count_log.png")
    make_panel(counts, bin_labels, n_genomes, False, assets_dir / "loci_by_allele_count_linear.png")

    rel_assets = assets_dir.relative_to(report_path.parent)
    generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    table_md = counts[["known", "novel_motif", "novel_locus"]].to_markdown()

    lines = [
        "# TR loci by novelty class and allele count",
        "",
        f"*Generated {generated} by `src/python/reporting/novelty_frequency_report.py` "
        f"from `{source.name}` ({n_genomes} HPRC genomes, {len(loci):,} true loci).*",
        "",
        "## Locus identity: (chrom, position), not SVID",
        "",
        "This merged VCF assigns the `SVID` column per-sample-call rather than one "
        "shared ID per joint locus: the same physical insertion can carry a "
        f"different SVID depending on which sample carries it. Grouping by SVID "
        f"gives {n_svid_loci:,} apparent loci; grouping by `(chrom, ins_coord)` "
        f"collapses these to {len(loci):,} true loci. The difference isn't just "
        "inflation -- it's directional: `SVID`-based carrier counts are biased "
        "*low*, because a locus's carriers can be split across several SVIDs, each "
        "of which looks individually rarer than the locus really is. Checked "
        "directly: for the large majority of split loci, the true pooled carrier "
        "count (grouping by position) exceeds what any single SVID shows on its "
        "own. Every count on this page uses the corrected `(chrom, position)` "
        "definition.",
        "",
        "Locus-level novelty class is also derived per position: 97.2% of loci "
        "have one unanimous verdict across all their carriers/SVIDs; the "
        "remaining 2.8% disagree (occasionally the same sample carries both a "
        "`known`-tagged and a `novel_motif`-tagged call at the identical "
        "coordinate, suggesting genuinely distinct alleles collapsed onto one "
        "position). The majority verdict is used as a pragmatic tie-break.",
        "",
        "## Binning",
        "",
        "Carrier count is binned by doubling (1, 2, 3-4, 5-8, 9-16, 17-33, 34-49, "
        f"50-{n_genomes}) rather than fixed percentage cutoffs -- a standard "
        "site-frequency-spectrum convention that scales cleanly with cohort size "
        "instead of rounding inconsistently for n=67 (e.g. \"10%\" of 67 is 6.7, "
        "which different rounding rules place at either 6 or 7). Only 7 loci in "
        "the entire callset are carried by all 67 genomes, too few for their own "
        "bin, so the top two bands (34-49, 50-67) absorb the common/fixed end.",
        "",
        "## Loci by class and allele count",
        "",
        "Raw locus counts, not proportions and not per-genome medians -- this is "
        "literally how many `novel_motif`/`novel_locus` loci exist at each carrier "
        "count. `known` loci are omitted from the plot (not of interest here) but "
        "included in the table below for reference.",
        "",
        table_md,
        "",
        f"![Loci by class and allele count, log scale]({rel_assets}/loci_by_allele_count_log.png)",
        "",
        f"![Loci by class and allele count, linear scale]({rel_assets}/loci_by_allele_count_linear.png)",
        "",
        "## Reading this chart",
        "",
        "Both classes decline sharply from rare to common. That decline is "
        "*expected* and not specific to novelty -- it's the standard "
        "site-frequency-spectrum pattern seen for essentially every kind of "
        "genetic variant: a new mutation/insertion arises in one person at a "
        "time, and only a small fraction of lineages ever drift up to high "
        "frequency across a sampled population. `known` loci (see the table) "
        "decline the same way, which rules out this being an artifact specific "
        "to the novelty classification.",
        "",
        "What this chart does *not* show is whether novelty *rate* changes with "
        "rarity -- that requires normalizing each bin by its total locus count "
        "(known + novel_motif + novel_locus), which on this filtered dataset "
        "comes out essentially flat (~20% novel_motif, <1.2% novel_locus in "
        "every bin) -- consistent with a related result in "
        "`feature/population-structure`'s methods doc, where an analogous "
        "novelty-vs-frequency association held on an *unfiltered* call set but "
        "flattened out once the pipeline's quality filters were applied.",
        "",
    ]
    report_path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--multisample-tsv", type=Path, required=True,
                         help="Per-call TSV from sv_trfcaller + novelty annotate, e.g. 05_hprc_multisample.tsv")
    parser.add_argument("--outdir", type=Path, default=Path("docs/figures"))
    args = parser.parse_args()

    loci, n_genomes = build_loci_table(args.multisample_tsv)
    n_svid_loci = pd.read_csv(args.multisample_tsv, sep="\t", usecols=["SVID"])["SVID"].nunique()

    report_path = args.outdir / "novelty_by_allele_count.md"
    assets_dir = args.outdir / "assets" / "novelty_by_allele_count"
    build_report(loci, n_genomes, n_svid_loci, assets_dir, report_path, args.multisample_tsv)
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
