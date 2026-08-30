"""
Analyze hprc_multisample.trf.noveltyFiltered.tsv:
  1. Novelty burden by ancestry (ucsc_novelty vs trexplorer_novelty, pooled raw totals)
  2. Locus/motif landscape overview (ancestry-independent)

See data_summary_notes.md for the data description and the plan this implements.
Outputs PNG charts + a couple of summary TSVs into 2026/figures/.
"""
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

HERE = Path(__file__).parent
FIG_DIR = HERE / "figures"
FIG_DIR.mkdir(exist_ok=True)

TSV_PATH = HERE / "hprc_multisample.trf.noveltyFiltered.tsv"
ANCESTRY_PATH = HERE / "HPRC_samples_ancestry.tsv"

# --- dataviz skill palette (references/palette.md) ---
CAT = {
    "blue": "#2a78d6",
    "orange": "#eb6834",
    "aqua": "#1baf7a",
    "yellow": "#eda100",
    "magenta": "#e87ba4",
    "green": "#008300",
    "violet": "#4a3aa7",
    "red": "#e34948",
}
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
SURFACE = "#fcfcfb"

# Novelty categories: fixed hue order, never cycled (categorical = identity).
# Use palette slots 1-3 in their documented order (blue, orange, aqua) for the
# three real categories; 'unscreened' is a data-quality flag, not a comparable
# category, so it gets muted ink rather than a fifth categorical hue.
NOVELTY_ORDER = ["known", "novel_locus", "novel_motif", "unscreened"]
NOVELTY_COLORS = {
    "known": CAT["blue"],
    "novel_locus": CAT["orange"],
    "novel_motif": CAT["aqua"],
    "unscreened": INK_MUTED,
}

# Ancestry: fixed hue order, never cycled - palette slots 1-5 in documented order
ANCESTRY_ORDER = ["AFR", "AMR", "EAS", "EUR", "SAS"]
ANCESTRY_COLORS = {
    "AFR": CAT["blue"],
    "AMR": CAT["orange"],
    "EAS": CAT["aqua"],
    "EUR": CAT["yellow"],
    "SAS": CAT["magenta"],
}

SEQUENTIAL_BLUES = ["#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6", "#184f95"]

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "axes.edgecolor": BASELINE,
    "axes.labelcolor": INK_PRIMARY,
    "text.color": INK_PRIMARY,
    "xtick.color": INK_PRIMARY,
    "ytick.color": INK_PRIMARY,
    "xtick.labelcolor": INK_PRIMARY,
    "ytick.labelcolor": INK_PRIMARY,
    "axes.labelsize": 11,
    "xtick.labelsize": 11,
    "ytick.labelsize": 11,
    "grid.color": GRIDLINE,
    "font.family": "sans-serif",
    "axes.grid": True,
    "grid.linewidth": 0.6,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.spines.left": False,
    "axes.axisbelow": True,
})


def load_data():
    df = pd.read_csv(TSV_PATH, sep="\t")
    ancestry = pd.read_csv(
        ANCESTRY_PATH, sep="\t", header=None,
        names=["sample", "sex", "population"],
    )

    keep_chroms = {f"chr{i}" for i in range(1, 23)} | {"chrX", "chrY"}
    n_before = len(df)
    df = df[df["chrom"].isin(keep_chroms)].copy()
    print(f"Scope filter: kept {len(df):,}/{n_before:,} rows "
          f"(chr1-22, X, Y; dropped alt/random contigs)")

    df = df.merge(ancestry, left_on="sample", right_on="sample", how="left")
    missing = df["population"].isna().sum()
    if missing:
        print(f"WARNING: {missing} rows have no ancestry match")

    df["population"] = pd.Categorical(df["population"], categories=ANCESTRY_ORDER, ordered=True)
    for col in ["novelty", "ucsc_novelty", "trexplorer_novelty"]:
        df[col] = pd.Categorical(df[col], categories=NOVELTY_ORDER, ordered=True)
    return df, ancestry


def style_bar_axis(ax):
    ax.grid(axis="x", linewidth=0.6)
    ax.grid(axis="y", visible=False)
    ax.tick_params(length=0)


def plot_novelty_by_ancestry(df, ancestry):
    """Section 1: stacked + grouped bars, pooled raw totals per ancestry group."""
    sample_n = ancestry.groupby("population").size().reindex(ANCESTRY_ORDER)
    stack_order = ["known", "novel_motif", "novel_locus", "unscreened"]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), sharey=True)
    for ax, col, title in zip(
        axes, ["ucsc_novelty", "trexplorer_novelty"],
        ["UCSC Simple Repeats", "TRExplorer"],
    ):
        counts = (
            df.groupby(["population", col], observed=False)
            .size()
            .unstack(col)
            .reindex(index=ANCESTRY_ORDER, columns=stack_order)
            .fillna(0)
        )
        bottom = pd.Series(0, index=counts.index, dtype=float)
        for cat in stack_order:
            if counts[cat].sum() == 0:
                continue
            ax.barh(
                counts.index, counts[cat], left=bottom,
                color=NOVELTY_COLORS[cat], label=cat,
                height=0.62, edgecolor=SURFACE, linewidth=2,
            )
            bottom += counts[cat]
        ax.set_title(title, color=INK_PRIMARY, fontsize=12, pad=10)
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
        style_bar_axis(ax)
        # annotate each bar with its sample n, since these are pooled totals
        for i, pop in enumerate(ANCESTRY_ORDER):
            ax.text(
                bottom[pop] + bottom.max() * 0.015, i, f"n={sample_n[pop]} samples",
                va="center", ha="left", fontsize=9, color=INK_PRIMARY,
            )

    axes[0].set_ylabel("Ancestry (1000G/IGSR superpopulation)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles, labels, loc="lower center", ncol=4, frameon=False,
        bbox_to_anchor=(0.5, -0.02),
    )
    fig.suptitle(
        "TR-insertion novelty by ancestry, pooled raw call counts\n"
        "(unequal group sizes - see per-bar sample n; not a per-sample rate)",
        color=INK_PRIMARY, fontsize=13,
    )
    fig.tight_layout(rect=[0, 0.06, 1, 0.90])
    fig.savefig(FIG_DIR / "01_novelty_by_ancestry_stacked.png", dpi=160)
    plt.close(fig)

    # Companion table
    rows = []
    for col in ["ucsc_novelty", "trexplorer_novelty"]:
        counts = (
            df.groupby(["population", col], observed=False)
            .size()
            .unstack(col)
            .reindex(index=ANCESTRY_ORDER, columns=NOVELTY_ORDER)
            .fillna(0)
            .astype(int)
        )
        pct = counts.div(counts.sum(axis=1), axis=0) * 100
        for pop in ANCESTRY_ORDER:
            row = {"novelty_source": col, "population": pop, "n_samples": int(sample_n[pop])}
            for cat in NOVELTY_ORDER:
                row[f"{cat}_n"] = counts.loc[pop, cat]
                row[f"{cat}_pct"] = round(pct.loc[pop, cat], 1)
            rows.append(row)
    table = pd.DataFrame(rows)
    table.to_csv(FIG_DIR / "novelty_by_ancestry_table.tsv", sep="\t", index=False)

    # Companion loci table: same breakdown, but counting distinct (chrom,
    # ins_coord) loci per ancestry group instead of raw call rows. NOTE: a
    # locus carried by samples from more than one ancestry group is counted
    # in each of those groups - these counts are NOT additive across
    # populations (they will sum to more than the dataset's true total unique
    # loci wherever groups share a locus).
    loci_rows = []
    for col in ["ucsc_novelty", "trexplorer_novelty"]:
        for pop in ANCESTRY_ORDER:
            sub_pop = df[df["population"] == pop]
            row = {"novelty_source": col, "population": pop, "n_samples": int(sample_n[pop])}
            for cat in NOVELTY_ORDER:
                sub = sub_pop[sub_pop[col] == cat]
                row[f"{cat}_n_loci"] = sub[["chrom", "ins_coord"]].drop_duplicates().shape[0]
            loci_rows.append(row)
    loci_table = pd.DataFrame(loci_rows)
    loci_table.to_csv(FIG_DIR / "novelty_by_ancestry_loci_table.tsv", sep="\t", index=False)

    print("Wrote 01_novelty_by_ancestry_stacked.png + novelty_by_ancestry_table.tsv "
          "+ novelty_by_ancestry_loci_table.tsv")


def plot_grouped_disagreement(df, ancestry):
    """Companion grouped-bar view: UCSC vs TRExplorer side by side per ancestry group."""
    sample_n = ancestry.groupby("population").size().reindex(ANCESTRY_ORDER)
    cats_to_show = ["novel_locus", "novel_motif"]  # 'known' dominates and isn't the interesting signal here

    fig, axes = plt.subplots(1, len(cats_to_show), figsize=(12, 4.8), sharey=False)
    source_colors = {"ucsc_novelty": CAT["blue"], "trexplorer_novelty": CAT["orange"]}
    source_labels = {"ucsc_novelty": "UCSC", "trexplorer_novelty": "TRExplorer"}

    for ax, cat in zip(axes, cats_to_show):
        width = 0.38
        x = range(len(ANCESTRY_ORDER))
        for i, col in enumerate(["ucsc_novelty", "trexplorer_novelty"]):
            counts = (
                df[df[col] == cat]
                .groupby("population", observed=False)
                .size()
                .reindex(ANCESTRY_ORDER)
                .fillna(0)
            )
            offset = (i - 0.5) * width
            ax.bar(
                [xi + offset for xi in x], counts.values, width=width,
                color=source_colors[col], label=source_labels[col],
                edgecolor=SURFACE, linewidth=1.5,
            )
        ax.set_xticks(list(x))
        ax.set_xticklabels(
            [f"{p}\n(n={sample_n[p]})" for p in ANCESTRY_ORDER], fontsize=9,
        )
        ax.set_title(f'"{cat}" calls, pooled', color=INK_PRIMARY, fontsize=11)
        ax.grid(axis="y", linewidth=0.6)
        ax.grid(axis="x", visible=False)
        ax.tick_params(length=0)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(0.5, -0.03))
    fig.suptitle(
        "UCSC vs TRExplorer disagreement by ancestry (pooled raw counts)",
        color=INK_PRIMARY, fontsize=13,
    )
    fig.tight_layout(rect=[0, 0.08, 1, 0.90])
    fig.savefig(FIG_DIR / "02_novelty_source_disagreement_by_ancestry.png", dpi=160)
    plt.close(fig)
    print("Wrote 02_novelty_source_disagreement_by_ancestry.png")


def _plot_motif_length_panels(data, long_scale, out_name):
    import numpy as np

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # Short motifs (1-6bp: mono- through hexanucleotide repeats), one bar per
    # integer length - this range is where nearly all calls live, so a linear
    # axis is readable without a log transform.
    short = data[(data >= 1) & (data <= 6)]
    bins = list(range(1, 8))  # edges 1..7 -> bars centered on 1..6
    axes[0].hist(short, bins=bins, color=CAT["blue"], edgecolor=SURFACE, linewidth=0.8, align="left")
    axes[0].set_xticks(range(1, 7))
    axes[0].set_xlabel("Motif length (bp)")
    axes[0].set_ylabel("Number of TR calls")
    axes[0].set_title("1-6bp", color=INK_PRIMARY, fontsize=12)

    # Longer motifs (7bp+): heavily right-skewed (up to 392bp).
    long_ = data[data >= 7]
    if long_scale == "log":
        bins = [7, 10, 15, 20, 30, 50, 100, 200, 400]
        axes[1].hist(long_, bins=bins, color=CAT["orange"], edgecolor=SURFACE, linewidth=0.8)
        axes[1].set_xscale("log")
        axes[1].set_xlabel("Motif length (bp, log scale)")
    else:
        bins = np.linspace(7, long_.max(), 40)
        axes[1].hist(long_, bins=bins, color=CAT["orange"], edgecolor=SURFACE, linewidth=0.8)
        axes[1].set_xlabel("Motif length (bp)")
    axes[1].set_title("7bp+", color=INK_PRIMARY, fontsize=12)

    for ax in axes:
        style_bar_axis(ax)
        ax.grid(axis="x", visible=False)
        ax.grid(axis="y", linewidth=0.6)

    fig.suptitle("Motif length distribution", color=INK_PRIMARY, fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(FIG_DIR / out_name, dpi=160)
    plt.close(fig)
    print(f"Wrote {out_name}")


def _plot_motif_length_linear_broken(data, out_name):
    """1-6bp panel + a broken-axis 7bp+ panel: 0-100bp shown in full linear
    detail, then a compressed cutoff segment out to the max (~390bp) so the
    handful of very long motifs (only 150 calls are >100bp, out of ~52k in
    the 7bp+ range) don't force the whole axis to stretch to 392."""
    import numpy as np

    fig = plt.figure(figsize=(12, 5))
    outer = fig.add_gridspec(1, 2, width_ratios=[1, 1], wspace=0.3)
    tail_gs = outer[1].subgridspec(1, 2, width_ratios=[3, 1], wspace=0.06)
    ax_short = fig.add_subplot(outer[0])
    ax_tail = fig.add_subplot(tail_gs[0])
    ax_tail_far = fig.add_subplot(tail_gs[1], sharey=ax_tail)

    short = data[(data >= 1) & (data <= 6)]
    bins = list(range(1, 8))  # edges 1..7 -> bars centered on 1..6
    ax_short.hist(short, bins=bins, color=CAT["blue"], edgecolor=SURFACE, linewidth=0.8, align="left")
    ax_short.set_xticks(range(1, 7))
    ax_short.set_xlabel("Motif length (bp)")
    ax_short.set_ylabel("Number of TR calls")
    ax_short.set_title("1-6bp", color=INK_PRIMARY, fontsize=12)

    long_ = data[data >= 7]
    edges = np.linspace(7, long_.max(), 40)
    counts, edges = np.histogram(long_, bins=edges)
    widths = np.diff(edges)
    lefts = edges[:-1]

    for ax in (ax_tail, ax_tail_far):
        ax.bar(lefts, counts, width=widths, align="edge", color=CAT["orange"], edgecolor=SURFACE, linewidth=0.6)

    ax_tail.set_xlim(0, 100)
    ax_tail_far.set_xlim(100, 392)
    ax_tail_far.set_xticks([390])
    ax_tail.set_xlabel("Motif length (bp)")
    ax_tail.set_title("7bp+", color=INK_PRIMARY, fontsize=12)

    ax_tail.spines["right"].set_visible(False)
    ax_tail_far.spines["left"].set_visible(False)
    ax_tail_far.tick_params(labelleft=False)
    ax_tail_far.yaxis.set_visible(False)

    # diagonal break mark where the two tail axes meet - only at the bottom,
    # since the only visible spine in this style is the baseline (top/left/
    # right are off globally); a mark at the top would float with no spine
    # to attach to.
    d = 0.5
    kwargs = {
        "marker": [(-1, -d), (1, d)], "markersize": 10, "linestyle": "none",
        "color": BASELINE, "mec": BASELINE, "mew": 1.3, "clip_on": False,
    }
    ax_tail.plot([1], [0], transform=ax_tail.transAxes, **kwargs)
    ax_tail_far.plot([0], [0], transform=ax_tail_far.transAxes, **kwargs)

    for ax in (ax_short, ax_tail, ax_tail_far):
        style_bar_axis(ax)
        ax.grid(axis="x", visible=False)
        ax.grid(axis="y", linewidth=0.6)

    fig.suptitle("Motif length distribution (linear scale)", color=INK_PRIMARY, fontsize=13)
    # subplots_adjust (not tight_layout) - tight_layout doesn't understand the
    # manual subgridspec used for the broken axis and mis-places the panels
    fig.subplots_adjust(left=0.07, right=0.97, top=0.85, bottom=0.15)
    fig.savefig(FIG_DIR / out_name, dpi=160)
    plt.close(fig)
    print(f"Wrote {out_name}")


def plot_motif_length_hist(df):
    data = df["motif_length"].dropna()
    for stale in [
        "03a_motif_length_hist_1to7.png",
        "03b_motif_length_hist_7plus.png",
        "03_motif_length_hist_linear_categorized.png",
    ]:
        stale_path = FIG_DIR / stale
        if stale_path.exists():
            stale_path.unlink()

    _plot_motif_length_panels(data, long_scale="log", out_name="03_motif_length_hist.png")
    _plot_motif_length_linear_broken(data, out_name="03_motif_length_hist_linear.png")


def plot_rep_length_and_units(df):
    # Both fields are heavily right-skewed (most calls are short/low-copy-number
    # with a long tail) - a linear-bin histogram crams ~90% of mass into one bin,
    # so use log-spaced bins on a log x-axis, as with motif_length.
    import numpy as np

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    rep_len = df["rep_length"].dropna()
    rep_len = rep_len[rep_len > 0]
    bins_len = np.logspace(0, np.log10(rep_len.max()), 40)
    axes[0].hist(rep_len, bins=bins_len, color=CAT["blue"], edgecolor=SURFACE, linewidth=0.5)
    axes[0].set_xscale("log")
    axes[0].set_xlabel("Repeat tract length (bp, log scale)")
    axes[0].set_ylabel("Number of TR calls")
    axes[0].set_title("Repeat tract length", color=INK_PRIMARY, fontsize=12)

    rep_units = df["rep_units"].dropna()
    rep_units = rep_units[rep_units > 0]
    bins_units = np.logspace(0, np.log10(rep_units.max()), 40)
    axes[1].hist(rep_units, bins=bins_units, color=CAT["orange"], edgecolor=SURFACE, linewidth=0.5)
    axes[1].set_xscale("log")
    axes[1].set_xlabel("Repeat copy number (rep_units, log scale)")
    axes[1].set_title("Repeat copy number", color=INK_PRIMARY, fontsize=12)

    for ax in axes:
        style_bar_axis(ax)
        ax.grid(axis="x", visible=False)
        ax.grid(axis="y", linewidth=0.6)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "04_rep_length_and_units_hist.png", dpi=160)
    plt.close(fig)
    print("Wrote 04_rep_length_and_units_hist.png")


def plot_purity(df):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].hist(
        df["purity"].dropna(), bins=40, color=CAT["blue"],
        edgecolor=SURFACE, linewidth=0.5,
    )
    axes[0].set_xlabel("purity (reference TR match)")
    axes[0].set_ylabel("Number of TR calls")
    axes[0].set_title("TRF purity", color=INK_PRIMARY, fontsize=12)

    axes[1].hist(
        df["insertion_purity"].dropna(), bins=40, color=CAT["orange"],
        edgecolor=SURFACE, linewidth=0.5,
    )
    axes[1].set_xlabel("insertion_purity")
    axes[1].set_title("Insertion purity", color=INK_PRIMARY, fontsize=12)

    for ax in axes:
        style_bar_axis(ax)
        ax.grid(axis="x", visible=False)
        ax.grid(axis="y", linewidth=0.6)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "05_purity_hist.png", dpi=160)
    plt.close(fig)
    print("Wrote 05_purity_hist.png")


def plot_top_motifs(df, top_n=15):
    fig, ax = plt.subplots(figsize=(8, 7))
    top = df["canonical_motif"].value_counts().head(top_n).sort_values()
    ax.barh(top.index.astype(str), top.values, color=CAT["blue"], edgecolor=SURFACE, linewidth=0.8)
    ax.set_xlabel("Number of TR calls")
    ax.set_title(f"Top {top_n} canonical motifs", color=INK_PRIMARY, fontsize=13)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    style_bar_axis(ax)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "06_top_canonical_motifs.png", dpi=160)
    plt.close(fig)
    print("Wrote 06_top_canonical_motifs.png")


def plot_top_motifs_by_unique_loci(df, top_n=15):
    """Companion to 06_top_canonical_motifs.png: ranks motifs by distinct
    (chrom, ins_coord) loci they occur at, not raw TR-call rows - a motif
    that recurs across many samples/SVIDs at the same handful of positions
    looks big in the per-call chart but should not look big here, and vice
    versa. Whole scoped dataset (all 3 novelty categories), not just
    novel_locus."""
    n_loci_by_motif = df.groupby("canonical_motif").apply(
        lambda d: d[["chrom", "ins_coord"]].drop_duplicates().shape[0], include_groups=False
    )
    top = n_loci_by_motif.sort_values(ascending=False).head(top_n).sort_values()

    fig, ax = plt.subplots(figsize=(8, 7))
    ax.barh(top.index.astype(str), top.values, color=CAT["orange"], edgecolor=SURFACE, linewidth=0.8)
    ax.set_xlabel("Number of unique loci (chrom:ins_coord)")
    ax.set_title(f"Top {top_n} canonical motifs by unique loci", color=INK_PRIMARY, fontsize=13)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    style_bar_axis(ax)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "06b_top_canonical_motifs_by_unique_loci.png", dpi=160)
    plt.close(fig)
    print("Wrote 06b_top_canonical_motifs_by_unique_loci.png")


def plot_overall_novelty_donut(df):
    import math

    fig, axes = plt.subplots(1, 2, figsize=(11, 5.5))
    footnotes = []
    for ax, col, title in zip(
        axes, ["ucsc_novelty", "trexplorer_novelty"],
        ["UCSC Simple Repeats", "TRExplorer"],
    ):
        # Only plot categories this source actually has (UCSC has no
        # 'unscreened' category at all - reindexing it in would draw a
        # dangling 0.0% label with no wedge behind it).
        counts = df[col].value_counts().reindex(NOVELTY_ORDER).fillna(0).astype(int)
        counts = counts[counts > 0]
        colors = [NOVELTY_COLORS[c] for c in counts.index]
        wedges, _ = ax.pie(
            counts.values, colors=colors, startangle=90,
            wedgeprops={"width": 0.42, "edgecolor": SURFACE, "linewidth": 2},
        )
        total = counts.sum()
        small_slices = []
        for w, cat, val in zip(wedges, counts.index, counts.values):
            pct = val / total * 100
            if pct < 1.5:
                # Too thin to label on-slice without collision/overlap; call
                # it out in a footnote instead of printing a misleading "0.x%"
                # floating near an invisible wedge.
                small_slices.append(f"{cat} {pct:.2f}% (n={val:,})")
                continue
            ang = (w.theta1 + w.theta2) / 2
            x, y = 0.78 * math.cos(math.radians(ang)), 0.78 * math.sin(math.radians(ang))
            ax.text(
                x, y, f"{cat}\n{pct:.1f}%", ha="center", va="center",
                fontsize=9, color=INK_PRIMARY,
            )
        ax.set_title(title, color=INK_PRIMARY, fontsize=12)
        if small_slices:
            footnotes.append(f"{title}: " + ", ".join(small_slices))

    if footnotes:
        fig.text(
            0.5, 0.02, "  |  ".join(footnotes), ha="center", va="bottom",
            fontsize=8.5, color=INK_PRIMARY,
        )
    fig.suptitle("Whole-dataset novelty split", color=INK_PRIMARY, fontsize=13)
    fig.tight_layout(rect=[0, 0.06, 1, 0.92])
    fig.savefig(FIG_DIR / "07_overall_novelty_split.png", dpi=160)
    plt.close(fig)
    print("Wrote 07_overall_novelty_split.png")


def plot_calls_per_chromosome(df):
    order = [f"chr{i}" for i in range(1, 23)] + ["chrX", "chrY"]
    counts = df["chrom"].value_counts().reindex(order).fillna(0)
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.bar(counts.index, counts.values, color=CAT["blue"], edgecolor=SURFACE, linewidth=0.8)
    ax.set_ylabel("Number of TR calls")
    ax.set_title("TR calls per chromosome (raw counts)", color=INK_PRIMARY, fontsize=13)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    style_bar_axis(ax)
    ax.grid(axis="x", visible=False)
    ax.grid(axis="y", linewidth=0.6)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "08_calls_per_chromosome.png", dpi=160)
    plt.close(fig)
    print("Wrote 08_calls_per_chromosome.png")


def plot_repeat_coverage(df):
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(
        df["repeat_coverage"].dropna(), bins=40, color=CAT["blue"],
        edgecolor=SURFACE, linewidth=0.5,
    )
    ax.set_xlabel("repeat_coverage (fraction of insertion explained by the repeat)")
    ax.set_ylabel("Number of TR calls")
    ax.set_title("Repeat coverage of the insertion", color=INK_PRIMARY, fontsize=13)
    style_bar_axis(ax)
    ax.grid(axis="x", visible=False)
    ax.grid(axis="y", linewidth=0.6)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "09_repeat_coverage_hist.png", dpi=160)
    plt.close(fig)
    print("Wrote 09_repeat_coverage_hist.png")


def summarize_trexplorer_novel_locus(df):
    """Deep-dive on trexplorer_novelty == 'novel_locus': how it compares to
    'known'/'novel_motif' on motif/purity/length characteristics, which
    motifs dominate it, and how concentrated it is on a small set of loci."""
    cats = ["known", "novel_locus", "novel_motif"]
    rows = []
    for cat in cats:
        sub = df[df["trexplorer_novelty"] == cat]
        rows.append({
            "category": cat,
            "n_calls": len(sub),
            "pct_of_total": round(len(sub) / len(df) * 100, 2),
            "n_unique_samples": sub["sample"].nunique(),
            # locus identity is (chrom, ins_coord), NOT SVID - SVID is not
            # 1:1 with genomic position (a handful of positions carry >1
            # SVID; see SVID-uniqueness note), so grouping by SVID undercounts
            # true locus recurrence.
            "n_unique_loci": len(sub[["chrom", "ins_coord"]].drop_duplicates()),
            "n_unique_canonical_motif": sub["canonical_motif"].nunique(),
            "motif_length_mean": round(sub["motif_length"].mean(), 1),
            "motif_length_median": sub["motif_length"].median(),
            "purity_mean": round(sub["purity"].mean(), 3),
            "purity_median": round(sub["purity"].median(), 3),
            "insertion_purity_mean": round(sub["insertion_purity"].mean(), 3),
            "rep_length_mean": round(sub["rep_length"].mean(), 1),
            "rep_length_median": sub["rep_length"].median(),
            "rep_units_mean": round(sub["rep_units"].mean(), 1),
            "rep_units_median": sub["rep_units"].median(),
            "repeat_coverage_mean": round(sub["repeat_coverage"].mean(), 3),
            "depth_mean": round(sub["depth"].mean(), 1),
            "depth_median": sub["depth"].median(),
        })
    comparison_table = pd.DataFrame(rows).set_index("category").T
    comparison_table.to_csv(FIG_DIR / "novel_locus_summary_by_trexplorer_category.tsv", sep="\t")

    nl = df[df["trexplorer_novelty"] == "novel_locus"]
    overall_counts = df["canonical_motif"].value_counts()
    overall_rank = {m: i + 1 for i, m in enumerate(overall_counts.index)}
    top_motifs = nl["canonical_motif"].value_counts().head(20)
    top_motifs_table = (
        top_motifs.rename("n_calls_in_novel_locus").reset_index()
        .rename(columns={"index": "canonical_motif"})
    )
    top_motifs_table["pct_of_novel_locus"] = round(
        top_motifs_table["n_calls_in_novel_locus"] / len(nl) * 100, 2
    )
    top_motifs_table["overall_rank_all_calls"] = top_motifs_table["canonical_motif"].map(overall_rank)

    # motif_length is constant per canonical_motif (verified: 0/155 motifs in
    # novel_locus have >1 distinct motif_length), so a direct lookup is exact;
    # rep_length varies per call, so report mean/median across that motif's calls.
    motif_length_by_motif = nl.groupby("canonical_motif")["motif_length"].first()
    rep_length_stats = nl.groupby("canonical_motif")["rep_length"].agg(["mean", "median"])
    top_motifs_table["motif_length"] = top_motifs_table["canonical_motif"].map(motif_length_by_motif)
    top_motifs_table["rep_length_mean"] = top_motifs_table["canonical_motif"].map(
        rep_length_stats["mean"]
    ).round(1)
    top_motifs_table["rep_length_median"] = top_motifs_table["canonical_motif"].map(
        rep_length_stats["median"]
    )
    # number of distinct (chrom, ins_coord) loci this motif appears at - a
    # motif can recur across many loci (e.g. AT spans 40), so this is not
    # the same as n_calls_in_novel_locus (which counts per-sample TR calls)
    n_loci_by_motif = nl.groupby("canonical_motif").apply(
        lambda d: d[["chrom", "ins_coord"]].drop_duplicates().shape[0], include_groups=False
    )
    top_motifs_table["n_unique_loci"] = top_motifs_table["canonical_motif"].map(n_loci_by_motif)
    top_motifs_table.to_csv(FIG_DIR / "novel_locus_trexplorer_top_motifs.tsv", sep="\t", index=False)

    # Locus = (chrom, ins_coord), NOT SVID: 229 unique loci vs 261 unique
    # SVID within novel_locus - 22 loci carry >1 distinct SVID, so grouping
    # by SVID splits a single locus's recurrence across multiple rows and
    # undercounts/misranks true locus-level recurrence. n_samples uses
    # nunique() (true distinct-sample count), separate from n_calls (raw row
    # count, which can exceed n_samples for homozygous calls that produce 2
    # identical rows per sample - see SVID-uniqueness note).
    per_locus = nl.groupby(["chrom", "ins_coord"]).agg(
        n_calls=("SVID", "size"),
        n_samples=("sample", "nunique"),
        n_unique_svid=("SVID", "nunique"),
        canonical_motif=("canonical_motif", "first"),
        motif_length=("motif_length", "first"),
    ).reset_index()
    top_loci = (
        per_locus.sort_values("n_samples", ascending=False).head(10)
        .assign(unique_loci=lambda d: d["chrom"] + ":" + d["ins_coord"].astype(str))
    )
    top_loci = top_loci[
        ["unique_loci", "chrom", "ins_coord", "canonical_motif", "motif_length",
         "n_unique_svid", "n_samples", "n_calls"]
    ]
    top_loci.to_csv(FIG_DIR / "novel_locus_trexplorer_most_recurrent_loci.tsv", sep="\t", index=False)

    print("Wrote novel_locus_summary_by_trexplorer_category.tsv, "
          "novel_locus_trexplorer_top_motifs.tsv, novel_locus_trexplorer_most_recurrent_loci.tsv")
    return comparison_table, top_motifs_table, top_loci


def _plot_novel_locus_depth(df, scale, out_name):
    """Visualize the depth outlier issue in trexplorer_novelty=='novel_locus':
    mean depth (43x) is pulled far above the median (36x) by a small number of
    extreme-depth calls (max 5,730x), which in long-read SV calling usually
    flags repetitive/multi-mapping regions rather than a clean single-copy locus."""
    import numpy as np

    nl = df[df["trexplorer_novelty"] == "novel_locus"]
    depth = nl["depth"].dropna()

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5), gridspec_kw={"width_ratios": [2, 1]})

    if scale == "log":
        bins = np.logspace(np.log10(depth.min()), np.log10(depth.max()), 30)
    else:
        bins = np.linspace(depth.min(), depth.max(), 30)
    axes[0].hist(depth, bins=bins, color=CAT["blue"], edgecolor=SURFACE, linewidth=0.6)
    if scale == "log":
        axes[0].set_xscale("log")
    axes[0].axvline(depth.median(), color=INK_PRIMARY, linestyle="--", linewidth=1)
    axes[0].text(
        depth.median(), axes[0].get_ylim()[1] * 0.95, f" median={depth.median():.0f}x",
        color=INK_PRIMARY, fontsize=9, va="top",
    )
    axes[0].set_xlabel(f"depth ({scale} scale)" if scale == "log" else "depth")
    axes[0].set_ylabel("Number of TR calls")
    axes[0].set_title("Distribution", color=INK_PRIMARY, fontsize=12)

    bp = axes[1].boxplot(
        depth, vert=True, widths=0.5, patch_artist=True,
        boxprops={"facecolor": CAT["blue"], "edgecolor": INK_PRIMARY},
        medianprops={"color": INK_PRIMARY, "linewidth": 1.5},
        whiskerprops={"color": INK_PRIMARY},
        capprops={"color": INK_PRIMARY},
        flierprops={
            "marker": "o", "markerfacecolor": CAT["red"], "markeredgecolor": CAT["red"],
            "markersize": 5, "alpha": 0.5,
        },
    )
    if scale == "log":
        axes[1].set_yscale("log")
    axes[1].set_xticks([])
    axes[1].set_ylabel(f"depth ({scale} scale)" if scale == "log" else "depth")
    axes[1].set_title(f"Outliers (n={len(bp['fliers'][0].get_ydata())})", color=INK_PRIMARY, fontsize=12)

    max_row = nl.loc[nl["depth"].idxmax()]
    axes[1].annotate(
        f"max={int(max_row['depth'])}x\n{max_row['sample']}\n{max_row['chrom']}:{int(max_row['ins_coord']):,}",
        xy=(1, max_row["depth"]), xytext=(1.15, max_row["depth"]),
        fontsize=8.5, color=INK_PRIMARY, va="center",
    )

    for ax in axes:
        style_bar_axis(ax)
        ax.grid(axis="x", visible=False)
        ax.grid(axis="y", linewidth=0.6)

    fig.suptitle(
        "novel_locus (TRExplorer): read depth at the insertion site",
        color=INK_PRIMARY, fontsize=13,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(FIG_DIR / out_name, dpi=160)
    plt.close(fig)
    print(f"Wrote {out_name}")


def _plot_novel_locus_depth_outliers_broken(df, out_name, cutoff=400, far_start=5000):
    """Linear-scale version of the depth-outlier chart (raw per-call depth,
    not per-locus median), with the same broken-axis treatment used for
    novel_locus_trexplorer_depth_distribution_linear.png: 0-cutoff in full linear detail,
    then a compressed far_start+ segment for the single ~5,730x outlier."""
    nl = df[df["trexplorer_novelty"] == "novel_locus"]
    depth = nl["depth"].dropna()
    data_max = depth.max()

    fig = plt.figure(figsize=(12, 5.5))
    outer = fig.add_gridspec(1, 2, width_ratios=[2, 1], wspace=0.3)
    hist_gs = outer[0].subgridspec(1, 2, width_ratios=[3, 1], wspace=0.06)
    box_gs = outer[1].subgridspec(2, 1, height_ratios=[1, 3], hspace=0.06)

    ax_hist_main = fig.add_subplot(hist_gs[0])
    ax_hist_far = fig.add_subplot(hist_gs[1], sharey=ax_hist_main)
    ax_box_far = fig.add_subplot(box_gs[0])
    ax_box_main = fig.add_subplot(box_gs[1], sharex=ax_box_far)

    main_bins = list(range(0, cutoff + 20, 20))
    far_bins = [far_start, data_max + 50]
    for ax, bins in ((ax_hist_main, main_bins), (ax_hist_far, far_bins)):
        ax.hist(depth, bins=bins, color=CAT["blue"], edgecolor=SURFACE, linewidth=0.6)
    ax_hist_main.set_xlim(0, cutoff)
    ax_hist_main.set_xticks([0, 100, 200, 300])  # exclude `cutoff` - would collide with the far tick
    ax_hist_far.set_xlim(far_start, data_max + 50)
    ax_hist_far.set_xticks([far_start])
    ax_hist_main.axvline(depth.median(), color=INK_PRIMARY, linestyle="--", linewidth=1)
    ax_hist_main.text(
        depth.median(), ax_hist_main.get_ylim()[1] * 0.95, f" median={depth.median():.0f}x",
        color=INK_PRIMARY, fontsize=9, va="top",
    )
    ax_hist_main.set_xlabel("depth")
    ax_hist_main.set_ylabel("Number of TR calls")
    ax_hist_main.set_title("Distribution", color=INK_PRIMARY, fontsize=12)
    ax_hist_far.spines["left"].set_visible(False)
    ax_hist_far.tick_params(labelleft=False)
    _add_break_marks(ax_hist_main, ax_hist_far, "x")

    boxprops = {
        "vert": True, "widths": 0.5, "patch_artist": True,
        "boxprops": {"facecolor": CAT["blue"], "edgecolor": INK_PRIMARY},
        "medianprops": {"color": INK_PRIMARY, "linewidth": 1.5},
        "whiskerprops": {"color": INK_PRIMARY},
        "capprops": {"color": INK_PRIMARY},
        "flierprops": {
            "marker": "o", "markerfacecolor": CAT["red"], "markeredgecolor": CAT["red"],
            "markersize": 5, "alpha": 0.5,
        },
    }
    n_outliers = None
    for ax in (ax_box_main, ax_box_far):
        bp = ax.boxplot(depth, **boxprops)
        n_outliers = len(bp["fliers"][0].get_ydata())
    ax_box_main.set_ylim(0, cutoff)
    ax_box_main.set_yticks([0, 100, 200, 300])  # exclude `cutoff` - would collide with the far tick
    ax_box_far.set_ylim(far_start, far_start + 1500)  # headroom above the outlier for its label
    ax_box_far.set_yticks([far_start])
    ax_box_main.set_xticks([])
    ax_box_main.set_ylabel("depth")
    ax_box_far.set_title(f"Outliers (n={n_outliers})", color=INK_PRIMARY, fontsize=12)
    ax_box_far.spines["bottom"].set_visible(False)
    ax_box_far.tick_params(labelbottom=False, bottom=False)
    ax_box_main.spines["left"].set_visible(True)
    ax_box_far.spines["left"].set_visible(True)
    _add_break_marks(ax_box_main, ax_box_far, "y")

    max_row = nl.loc[nl["depth"].idxmax()]
    ax_box_far.annotate(
        f"max={int(max_row['depth'])}x\n{max_row['sample']}\n{max_row['chrom']}:{int(max_row['ins_coord']):,}",
        xy=(1, max_row["depth"]), xytext=(1.15, max_row["depth"]),
        fontsize=8.5, color=INK_PRIMARY, va="center",
    )

    for ax in (ax_hist_main, ax_hist_far, ax_box_main, ax_box_far):
        style_bar_axis(ax)
        ax.grid(axis="x", visible=False)
        ax.grid(axis="y", linewidth=0.6)

    fig.suptitle(
        "novel_locus (TRExplorer): read depth at the insertion site",
        color=INK_PRIMARY, fontsize=13,
    )
    fig.subplots_adjust(left=0.07, right=0.97, top=0.85, bottom=0.15)
    fig.savefig(FIG_DIR / out_name, dpi=160)
    plt.close(fig)
    print(f"Wrote {out_name}")


def plot_novel_locus_depth(df):
    _plot_novel_locus_depth(df, scale="log", out_name="novel_locus_trexplorer_depth_outliers.png")
    _plot_novel_locus_depth_outliers_broken(df, out_name="novel_locus_trexplorer_depth_outliers_linear.png")


def _plot_novel_locus_depth_distribution(df, scale, out_name):
    """Per-locus depth distribution for trexplorer_novelty=='novel_locus':
    one data point per unique locus (chrom, ins_coord) - median depth across
    the samples carrying that locus, not one point per TR-call row (which
    would let recurrent loci dominate the histogram just by having more rows).
    Left: histogram of median depth per locus (y = count of loci). Right:
    scatter of median depth vs. number of samples per locus, so recurrence
    is visible alongside depth."""
    import numpy as np

    nl = df[df["trexplorer_novelty"] == "novel_locus"]
    per_locus = nl.groupby(["chrom", "ins_coord"]).agg(
        median_depth=("depth", "median"),
        n_samples=("sample", "nunique"),
    ).reset_index()

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5))

    if scale == "log":
        bins = np.logspace(
            np.log10(per_locus["median_depth"].min()),
            np.log10(per_locus["median_depth"].max()), 25,
        )
    else:
        bins = np.linspace(per_locus["median_depth"].min(), per_locus["median_depth"].max(), 25)
    axes[0].hist(per_locus["median_depth"], bins=bins, color=CAT["blue"], edgecolor=SURFACE, linewidth=0.6)
    if scale == "log":
        axes[0].set_xscale("log")
    axes[0].set_xlabel(f"Median depth per locus ({scale} scale)" if scale == "log" else "Median depth per locus")
    axes[0].set_ylabel("Number of loci")
    axes[0].set_title("Distribution across loci", color=INK_PRIMARY, fontsize=12)

    axes[1].scatter(
        per_locus["n_samples"], per_locus["median_depth"],
        color=CAT["blue"], alpha=0.6, edgecolor=SURFACE, linewidth=0.4, s=40,
    )
    if scale == "log":
        axes[1].set_yscale("log")
    axes[1].set_xlabel("Number of samples carrying the locus")
    axes[1].set_ylabel(f"Median depth per locus ({scale} scale)" if scale == "log" else "Median depth per locus")
    axes[1].set_title("Depth vs. recurrence", color=INK_PRIMARY, fontsize=12)

    outlier = per_locus.loc[per_locus["median_depth"].idxmax()]
    axes[1].annotate(
        f"{outlier['chrom']}:{int(outlier['ins_coord']):,}\nmedian={int(outlier['median_depth'])}x, n={int(outlier['n_samples'])} sample(s)",
        xy=(outlier["n_samples"], outlier["median_depth"]),
        xytext=(outlier["n_samples"] + 3, outlier["median_depth"]),
        fontsize=8.5, color=INK_PRIMARY, va="center",
    )

    for ax in axes:
        style_bar_axis(ax)
        ax.grid(axis="x", visible=False)
        ax.grid(axis="y", linewidth=0.6)

    fig.suptitle(
        f"novel_locus (TRExplorer): per-locus depth (n={len(per_locus)} unique loci)",
        color=INK_PRIMARY, fontsize=13,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(FIG_DIR / out_name, dpi=160)
    plt.close(fig)
    print(f"Wrote {out_name}")


def _add_break_marks(ax_low, ax_high, orientation):
    """Diagonal break mark at the boundary between a low-range and a
    high-range axis. orientation='x' breaks a shared x-axis (marks on the
    bottom baseline, between the right edge of ax_low and left edge of
    ax_high) - the bottom spine is visible globally, so the marks have
    something to sit on. orientation='y' breaks a shared y-axis (marks on
    the left spine, between the top of ax_low and bottom of ax_high) - the
    left spine is OFF globally in this style, so the caller must explicitly
    re-enable it on both axes first, or the marks float with nothing to
    attach to."""
    d = 0.5
    kwargs = {
        "marker": [(-1, -d), (1, d)], "markersize": 10, "linestyle": "none",
        "color": BASELINE, "mec": BASELINE, "mew": 1.3, "clip_on": False,
    }
    if orientation == "x":
        ax_low.plot([1], [0], transform=ax_low.transAxes, **kwargs)
        ax_high.plot([0], [0], transform=ax_high.transAxes, **kwargs)
    else:
        rot_kwargs = dict(kwargs, marker=[(-0.5, -1), (0.5, 1)])
        ax_low.plot([0], [1], transform=ax_low.transAxes, **rot_kwargs)
        ax_high.plot([0], [0], transform=ax_high.transAxes, **rot_kwargs)


def _plot_novel_locus_depth_distribution_broken(df, out_name, cutoff=400, far_start=5000):
    """Linear-scale version of the per-locus depth distribution, with a
    broken axis: 0-cutoff shown in full linear detail, then a compressed
    segment for the far_start+ tail (here just the single ~5,730x outlier),
    so that one point doesn't force the whole axis to stretch to ~6000."""
    nl = df[df["trexplorer_novelty"] == "novel_locus"]
    per_locus = nl.groupby(["chrom", "ins_coord"]).agg(
        median_depth=("depth", "median"),
        n_samples=("sample", "nunique"),
    ).reset_index()
    data_max = per_locus["median_depth"].max()

    fig = plt.figure(figsize=(12, 5.5))
    outer = fig.add_gridspec(1, 2, width_ratios=[1, 1], wspace=0.3)
    hist_gs = outer[0].subgridspec(1, 2, width_ratios=[3, 1], wspace=0.06)
    scatter_gs = outer[1].subgridspec(2, 1, height_ratios=[1, 3], hspace=0.06)

    ax_hist_main = fig.add_subplot(hist_gs[0])
    ax_hist_far = fig.add_subplot(hist_gs[1], sharey=ax_hist_main)
    ax_scatter_far = fig.add_subplot(scatter_gs[0])
    ax_scatter_main = fig.add_subplot(scatter_gs[1], sharex=ax_scatter_far)

    main_bins = list(range(0, cutoff + 20, 20))
    far_bins = [far_start, data_max + 50]
    for ax, bins in ((ax_hist_main, main_bins), (ax_hist_far, far_bins)):
        ax.hist(per_locus["median_depth"], bins=bins, color=CAT["blue"], edgecolor=SURFACE, linewidth=0.6)
    ax_hist_main.set_xlim(0, cutoff)
    ax_hist_main.set_xticks([0, 100, 200, 300])  # exclude `cutoff` itself - it would collide with the far tick
    ax_hist_far.set_xlim(far_start, data_max + 50)
    ax_hist_far.set_xticks([far_start])
    ax_hist_main.set_xlabel("Median depth per locus")
    ax_hist_main.set_ylabel("Number of loci")
    ax_hist_main.set_title("Distribution across loci", color=INK_PRIMARY, fontsize=12)
    ax_hist_far.spines["left"].set_visible(False)
    ax_hist_far.tick_params(labelleft=False)
    _add_break_marks(ax_hist_main, ax_hist_far, "x")

    for ax in (ax_scatter_main, ax_scatter_far):
        ax.scatter(
            per_locus["n_samples"], per_locus["median_depth"],
            color=CAT["blue"], alpha=0.6, edgecolor=SURFACE, linewidth=0.4, s=40,
        )
    ax_scatter_main.set_ylim(0, cutoff)
    ax_scatter_main.set_yticks([0, 100, 200, 300])  # exclude `cutoff` - would collide with the far tick
    ax_scatter_far.set_ylim(far_start, far_start + 1500)  # headroom above the one outlier point for its label
    ax_scatter_far.set_yticks([far_start])
    ax_scatter_main.set_xlabel("Number of samples carrying the locus")
    ax_scatter_main.set_ylabel("Median depth per locus")
    ax_scatter_far.set_title("Depth vs. recurrence", color=INK_PRIMARY, fontsize=12)
    ax_scatter_far.spines["bottom"].set_visible(False)
    ax_scatter_far.tick_params(labelbottom=False, bottom=False)
    # this style has no left spine by default (only a bottom baseline) - a
    # y-axis break needs one to attach its marks to, so add it back just here
    ax_scatter_main.spines["left"].set_visible(True)
    ax_scatter_far.spines["left"].set_visible(True)
    _add_break_marks(ax_scatter_main, ax_scatter_far, "y")

    outlier = per_locus.loc[per_locus["median_depth"].idxmax()]
    ax_scatter_far.annotate(
        f"{outlier['chrom']}:{int(outlier['ins_coord']):,}\nmedian={int(outlier['median_depth'])}x, n={int(outlier['n_samples'])} sample(s)",
        xy=(outlier["n_samples"], outlier["median_depth"]),
        xytext=(outlier["n_samples"] + 3, outlier["median_depth"]),
        fontsize=8.5, color=INK_PRIMARY, va="center",
    )

    for ax in (ax_hist_main, ax_hist_far, ax_scatter_main, ax_scatter_far):
        style_bar_axis(ax)
        ax.grid(axis="x", visible=False)
        ax.grid(axis="y", linewidth=0.6)

    fig.suptitle(
        f"novel_locus (TRExplorer): per-locus depth (n={len(per_locus)} unique loci)",
        color=INK_PRIMARY, fontsize=13,
    )
    fig.subplots_adjust(left=0.07, right=0.97, top=0.85, bottom=0.15)
    fig.savefig(FIG_DIR / out_name, dpi=160)
    plt.close(fig)
    print(f"Wrote {out_name}")


def plot_novel_locus_depth_distribution(df):
    _plot_novel_locus_depth_distribution(df, scale="log", out_name="novel_locus_trexplorer_depth_distribution.png")
    _plot_novel_locus_depth_distribution_broken(df, out_name="novel_locus_trexplorer_depth_distribution_linear.png")


def main():
    df, ancestry = load_data()

    # Section 1: novelty burden by ancestry
    plot_novelty_by_ancestry(df, ancestry)
    plot_grouped_disagreement(df, ancestry)

    # Section 2: locus/motif landscape overview
    plot_motif_length_hist(df)
    plot_rep_length_and_units(df)
    plot_purity(df)
    plot_top_motifs(df)
    plot_top_motifs_by_unique_loci(df)
    plot_overall_novelty_donut(df)
    plot_calls_per_chromosome(df)
    plot_repeat_coverage(df)

    # Section 3: trexplorer_novelty == novel_locus deep dive
    summarize_trexplorer_novel_locus(df)
    plot_novel_locus_depth(df)
    plot_novel_locus_depth_distribution(df)

    print(f"\nAll figures written to {FIG_DIR}/")


if __name__ == "__main__":
    main()
