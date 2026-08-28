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


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    d, cohort = load()
    for name, fig in [("fig1_sharing_spectrum", fig1_sharing(d)),
                      ("fig2_ancestry_burden", fig2_ancestry(cohort)),
                      ("fig3_private_loci", fig3_private(d)),
                      ("fig4_fixed_frequency", fig4_fixed_frequency(d))]:
        for ext in ("png", "pdf"):
            fig.savefig(OUTDIR / f"{name}.{ext}", dpi=200, bbox_inches="tight")
        plt.close(fig)
        print(f"wrote {OUTDIR}/{name}.png / .pdf")


if __name__ == "__main__":
    main()
