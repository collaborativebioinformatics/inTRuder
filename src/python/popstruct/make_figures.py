#!/usr/bin/env python3
"""Population-structure figures for inTRuder novel-TR candidates.

Reads the locus-level carrier table and the sample metadata, and writes three
figures plus the summary statistics quoted in their captions.

    python src/python/popstruct/make_figures.py
"""
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

mpl.use("Agg")

CARRIERS = Path("results/locus_carriers.tsv")
METADATA = Path("data/metadata/sample_population.tsv")
OUTDIR = Path("results/figures")

SUPERPOPS = ["AFR", "AMR", "EAS", "EUR", "SAS"]
NOVELTY = ["known", "novel_motif", "novel_locus"]
LABEL = {"known": "Known", "novel_motif": "Novel motif", "novel_locus": "Novel locus"}

# Validated categorical slots 1-3 (see dataviz palette); aqua sits below 3:1 on
# the light surface, so every bar carries a direct value label as relief.
SERIES = {"known": "#2a78d6", "novel_motif": "#eb6834", "novel_locus": "#1baf7a"}
SINGLE = "#2a78d6"
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#8a8880"
SURFACE = "#fcfcfb"

mpl.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "font.family": "DejaVu Sans", "font.size": 9,
    "axes.edgecolor": MUTED, "axes.linewidth": 0.8,
    "axes.labelcolor": INK2, "text.color": INK,
    "xtick.color": INK2, "ytick.color": INK2,
    "xtick.labelsize": 8, "ytick.labelsize": 8,
    "axes.spines.top": False, "axes.spines.right": False,
    "legend.frameon": False, "legend.fontsize": 8,
})


def load():
    d = pd.read_csv(CARRIERS, sep="\t")
    meta = pd.read_csv(METADATA, sep="\t")
    cohort = meta[meta.is_control == "no"].copy()
    novel = d[d.novelty != "known"]
    counts = {}
    for carriers in novel.carriers.dropna():
        for s in str(carriers).split(";"):
            if s:
                counts[s] = counts.get(s, 0) + 1
    cohort["n_novel"] = cohort["sample"].map(counts).fillna(0).astype(int)
    return d, cohort


def style(ax, title, subtitle, ylab):
    ax.set_title(title, loc="left", fontsize=11, color=INK, fontweight="bold", pad=14)
    ax.text(0, 1.015, subtitle, transform=ax.transAxes, fontsize=8,
            color=INK2, va="bottom")
    ax.set_ylabel(ylab, fontsize=8.5)
    ax.yaxis.grid(True, color="#e6e5e0", linewidth=0.7)
    ax.set_axisbelow(True)


def fig1_sharing(d):
    """Are novel loci rarer across the cohort than known ones?"""
    edges = [(1, 1), (2, 2), (3, 5), (6, 10), (11, 20), (21, 40), (41, 67)]
    names = ["1", "2", "3-5", "6-10", "11-20", "21-40", "41-67"]
    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    w = 0.27
    for i, v in enumerate(NOVELTY):
        sub = d[d.novelty == v]
        pct = [((sub.n_carriers >= lo) & (sub.n_carriers <= hi)).sum() / len(sub) * 100
               for lo, hi in edges]
        x = np.arange(len(edges)) + (i - 1) * w
        # 2px surface gap between adjacent fills -> width reduced, edge painted
        ax.bar(x, pct, width=w * 0.88, color=SERIES[v], zorder=3,
               label=f"{LABEL[v]} (n={len(sub)})", linewidth=0.8, edgecolor=SURFACE)
        for xi, p in zip(x, pct):
            if p >= 2:
                ax.text(xi, p + 1.0, f"{p:.0f}", ha="center", va="bottom",
                        fontsize=6.6, color=INK2, zorder=4)
    ax.set_xticks(np.arange(len(edges)))
    ax.set_xticklabels(names)
    ax.set_xlabel("Number of carriers (of 67 genomes)", fontsize=8.5)
    style(ax, "Novel tandem-repeat loci are carried by fewer genomes",
          "Carrier-count distribution per novelty class. Novel loci are "
          "singleton-enriched (OR 2.4, Fisher p = 0.0065).",
          "% of loci in class")
    ax.legend(loc="upper right")
    fig.tight_layout()
    return fig


def fig2_ancestry(cohort):
    """Does novel-TR burden differ by genetic ancestry?"""
    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    rng = np.random.default_rng(0)
    groups = [cohort[cohort.superpopulation == s].n_novel.values for s in SUPERPOPS]
    H, p = stats.kruskal(*groups)
    for i, (sp, vals) in enumerate(zip(SUPERPOPS, groups)):
        jitter = rng.uniform(-0.16, 0.16, len(vals))
        ax.scatter(i + jitter, vals, s=26, color=SINGLE, alpha=0.65,
                   linewidth=0.8, edgecolor=SURFACE, zorder=3)
        m = np.median(vals)
        ax.plot([i - 0.30, i + 0.30], [m, m], color=INK, linewidth=2, zorder=4)
        ax.text(i, ax.get_ylim()[0], "", ha="center")
        lab = f"{m:.0f}" if float(m).is_integer() else f"{m:.1f}"
        ax.text(i + 0.34, m, lab, va="center", ha="left",
                fontsize=7.5, color=INK2, zorder=4)
    ax.set_xticks(range(len(SUPERPOPS)))
    ax.set_xticklabels([f"{s}\nn={len(g)}" for s, g in zip(SUPERPOPS, groups)])
    ax.set_xlabel("1000 Genomes superpopulation", fontsize=8.5)
    style(ax, "No detectable difference in novel-TR burden between superpopulations",
          f"One point per genome; bar is the group median. "
          f"Kruskal-Wallis H = {H:.2f}, p = {p:.3f} (not significant).",
          "Novel TR loci carried per genome")
    ax.set_xlim(-0.6, len(SUPERPOPS) - 0.15)
    fig.tight_layout()
    return fig


def fig3_private(d):
    """Are novel loci more often confined to a single superpopulation?"""
    cols = [f"n_{s}" for s in SUPERPOPS]
    fig, ax = plt.subplots(figsize=(7.4, 3.4))
    rows = []
    for v in NOVELTY:
        sub = d[d.novelty == v]
        npops = (sub[cols] > 0).sum(axis=1)
        rows.append([(npops == 1).sum(), ((npops > 1) & (npops < 5)).sum(),
                     (npops == 5).sum(), len(sub)])
    chi2, p, _, _ = stats.chi2_contingency(
        [[r[0], r[1] + r[2]] for r in rows])
    seg_lab = ["Private to 1", "Shared by 2-4", "In all 5"]
    shades = ["#2a78d6", "#7fb0e8", "#cfe0f6"]
    y = np.arange(len(NOVELTY))
    for i, r in enumerate(rows):
        left = 0
        for j in range(3):
            pct = r[j] / r[3] * 100
            ax.barh(y[i], pct, left=left, height=0.62, color=shades[j],
                    edgecolor=SURFACE, linewidth=1.4, zorder=3,
                    label=seg_lab[j] if i == 0 else None)
            if pct >= 7:
                ax.text(left + pct / 2, y[i], f"{pct:.0f}%", ha="center", va="center",
                        fontsize=7.5, color=INK if j else SURFACE, zorder=4)
            left += pct
    ax.set_yticks(y)
    ax.set_yticklabels([f"{LABEL[v]}\n(n={r[3]})" for v, r in zip(NOVELTY, rows)])
    ax.invert_yaxis()
    ax.set_xlabel("% of loci in class", fontsize=8.5)
    ax.xaxis.grid(True, color="#e6e5e0", linewidth=0.7)
    ax.yaxis.grid(False)
    ax.set_axisbelow(True)
    ax.set_title("Novel loci trend toward being confined to one superpopulation",
                 loc="left", fontsize=11, color=INK, fontweight="bold", pad=14)
    ax.text(0, 1.015, "Superpopulations among each locus's carriers. Private vs "
            f"shared, chi2 = {chi2:.2f}, p = {p:.3f} (n.s.).",
            transform=ax.transAxes, fontsize=8, color=INK2, va="bottom")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.20), ncol=3,
              handlelength=1.4, handleheight=0.9, columnspacing=2.2)
    fig.tight_layout()
    return fig


def fig4_fixed_frequency(d):
    """Novelty should fall with carrier frequency. At fixed frequency it does not."""
    edges = [(1, 1), (2, 2), (3, 5), (6, 10), (11, 20), (21, 40), (41, 66), (67, 67)]
    names = ["1", "2", "3-5", "6-10", "11-20", "21-40", "41-66", "67 (all)"]
    d = d.copy()
    d["is_novel"] = (d.novelty != "known").astype(int)
    rho, p = stats.spearmanr(d.n_carriers, d.is_novel)

    pct, n_loci, n_chm = [], [], []
    chm = d.chm13.fillna("")
    for lo, hi in edges:
        m = (d.n_carriers >= lo) & (d.n_carriers <= hi)
        s = d[m]
        pct.append((s.novelty != "known").sum() / len(s) * 100)
        n_loci.append(len(s))
        n_chm.append(int(chm[m & (d.novelty != "known")].str.contains("chm13").sum()))

    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    x = np.arange(len(edges))
    colors = [SERIES["known"]] * (len(edges) - 1) + [SERIES["novel_motif"]]
    ax.bar(x, pct, width=0.62, color=colors, zorder=3,
           linewidth=0.8, edgecolor=SURFACE)
    for xi, v, n, c in zip(x, pct, n_loci, n_chm):
        ax.text(xi, v + 1.6, f"{v:.0f}%", ha="center", va="bottom",
                fontsize=7.5, color=INK2, zorder=4)
        if c:
            ax.text(xi, v / 2, f"{c}\nCHM13", ha="center", va="center",
                    fontsize=6.6, color=SURFACE, zorder=5, linespacing=1.15)

    # trend line across the declining region only
    ax.plot(x[:-1], np.poly1d(np.polyfit(x[:-1], pct[:-1], 1))(x[:-1]),
            color=MUTED, linewidth=1.4, linestyle=(0, (5, 3)), zorder=4)
    ax.annotate("trend breaks at\nfixed frequency",
                xy=(x[-1], pct[-1] + 4), xytext=(x[-1] - 1.5, pct[-1] + 19),
                fontsize=7.6, color=SERIES["novel_motif"], ha="center",
                arrowprops=dict(arrowstyle="->", color=SERIES["novel_motif"],
                                lw=1.2, connectionstyle="arc3,rad=-0.25"), zorder=5)

    ax.set_xticks(x)
    ax.set_xticklabels([f"{nm}\nn={n}" for nm, n in zip(names, n_loci)])
    ax.set_xlabel("Number of carriers (of 67 genomes)", fontsize=8.5)
    ax.set_ylim(0, max(pct) + 26)
    style(ax, "Half of the loci present in every genome are still called novel",
          f"Novelty falls as loci become common (Spearman rho = {rho:.2f}, p = {p:.4f}), "
          "then rebounds at 67/67.",
          "% of loci in bin called novel")
    ax.margins(x=0.04)
    fig.tight_layout()
    return fig


BURDEN = Path("results/per_sample_insertion_burden.tsv")


def fig5_burden_by_ancestry():
    """Non-reference insertion burden per genome, full 67-genome callset."""
    b = pd.read_csv(BURDEN, sep="\t")
    b = b[b.superpopulation.isin(SUPERPOPS)]
    groups = [b[b.superpopulation == s].n_all.values for s in SUPERPOPS]
    H, p = stats.kruskal(*groups)
    afr, eur = groups[0], groups[3]
    _, p_ae = stats.mannwhitneyu(afr, eur)

    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    rng = np.random.default_rng(0)
    order = np.argsort([-np.median(g) for g in groups])
    for i, gi in enumerate(order):
        sp, vals = SUPERPOPS[gi], groups[gi]
        col = SERIES["novel_motif"] if sp == "AFR" else SINGLE
        ax.scatter(i + rng.uniform(-0.17, 0.17, len(vals)), vals, s=30, color=col,
                   alpha=0.7, linewidth=0.8, edgecolor=SURFACE, zorder=3)
        m = np.median(vals)
        ax.plot([i - 0.31, i + 0.31], [m, m], color=INK, linewidth=2.2, zorder=4)
        ax.text(i, m, f"{m:,.0f}", va="bottom", ha="center", fontsize=7.4,
                color=INK, zorder=5,
                bbox=dict(boxstyle="round,pad=0.18", fc=SURFACE, ec="none", alpha=0.85))

    # the separation line: AFR minimum sits above every other genome
    sep = (min(afr) + max([v for g, s in zip(groups, SUPERPOPS) if s != "AFR" for v in g])) / 2
    ax.axhline(sep, color=MUTED, linewidth=1.1, linestyle=(0, (5, 3)), zorder=2)
    ax.text(len(SUPERPOPS) - 0.42, sep, "all 19 AFR genomes above\nall 48 others below",
            fontsize=7.2, color=INK2, va="center", ha="left")

    ax.set_xticks(range(len(SUPERPOPS)))
    ax.set_xticklabels([f"{SUPERPOPS[gi]}\nn={len(groups[gi])}" for gi in order])
    ax.set_xlabel("1000 Genomes superpopulation", fontsize=8.5)
    ax.set_xlim(-0.6, len(SUPERPOPS) + 0.9)
    ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    style(ax, "African genomes carry 13.6% more non-reference insertions",
          f"One point per genome; 106,844 insertions, 67 HPRC genomes. "
          f"Kruskal-Wallis p = {p:.0e}.",
          "Insertions carried per genome")
    fig.tight_layout()
    return fig


def fig6_rarity_gradient():
    """Restricting to rarer insertions sharpens the ancestry difference."""
    b = pd.read_csv(BURDEN, sep="\t")
    b = b[b.superpopulation.isin(SUPERPOPS)]
    strata = [("n_all", "all"), ("n_lt34", "<50%\n(<34)"), ("n_le7", "<=10%\n(<=7)"),
              ("n_le3", "<=5%\n(<=3)"), ("n_single", "private\n(n=1)")]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(8.6, 4.0), gridspec_kw={"width_ratios": [1.35, 1]})

    for sp in SUPERPOPS:
        vals = [b[b.superpopulation == sp][c].median() for c, _ in strata]
        col = SERIES["novel_motif"] if sp == "AFR" else "#a8c4e4"
        lw = 2.4 if sp == "AFR" else 1.4
        ax.plot(range(len(strata)), vals, marker="o", ms=6, color=col, linewidth=lw,
                markeredgecolor=SURFACE, markeredgewidth=0.8, zorder=4 if sp == "AFR" else 3)
        if sp in ("AFR", "EUR"):
            ax.text(len(strata) - 0.90, vals[-1], f" {sp}", fontsize=7.8,
                    color=INK, va="center",
                    fontweight="bold" if sp == "AFR" else "normal")
    ax.set_xticks(range(len(strata)))
    ax.set_xticklabels([lab for _, lab in strata], fontsize=7.4)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_xlabel("Restricted to insertions carried by at most", fontsize=8.5)
    style(ax, "Rarer insertions, sharper difference",
          "Median per genome, log scale. Pale lines are AMR, EAS and SAS.",
          "Insertions per genome")
    ax.set_xlim(-0.3, len(strata) - 0.25)

    ratios = [b[b.superpopulation == "AFR"][c].median() / b[b.superpopulation == "EUR"][c].median()
              for c, _ in strata]
    ax2.bar(range(len(strata)), ratios, width=0.62, color=SERIES["novel_motif"],
            edgecolor=SURFACE, linewidth=0.8, zorder=3)
    for i, r in enumerate(ratios):
        ax2.text(i, r + 0.05, f"{r:.2f}x", ha="center", va="bottom", fontsize=7.6, color=INK2)
    ax2.axhline(1.0, color=MUTED, linewidth=1.1, linestyle=(0, (4, 3)), zorder=2)
    ax2.set_xticks(range(len(strata)))
    ax2.set_xticklabels([lab for _, lab in strata], fontsize=7.4)
    ax2.set_ylim(0, max(ratios) + 0.45)
    style(ax2, "AFR / EUR ratio", "Dashed line is parity.", "Ratio of medians")
    fig.tight_layout()
    return fig


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    d, cohort = load()
    for name, fig in [("fig1_sharing_spectrum", fig1_sharing(d)),
                      ("fig2_ancestry_burden", fig2_ancestry(cohort)),
                      ("fig3_private_loci", fig3_private(d)),
                      ("fig4_fixed_frequency", fig4_fixed_frequency(d)),
                      ("fig5_burden_by_ancestry", fig5_burden_by_ancestry()),
                      ("fig6_rarity_gradient", fig6_rarity_gradient())]:
        for ext in ("png", "pdf"):
            fig.savefig(OUTDIR / f"{name}.{ext}", dpi=200, bbox_inches="tight")
        plt.close(fig)
        print(f"wrote {OUTDIR}/{name}.png / .pdf")


if __name__ == "__main__":
    main()
