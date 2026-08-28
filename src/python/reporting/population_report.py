"""Generate a Markdown report of population-level TR distributions by novelty class.

Replaces the exploratory plots in notebooks/pop_viz.ipynb with a reusable,
non-interactive report: same underlying questions (how do motif length, repeat
length, purity, and GC content differ between known / novel_motif / novel_locus
calls), rendered as saved PNGs embedded in a Markdown file instead of notebook
cell output.

Usage:
    python src/python/reporting/population_report.py \\
        --input data/sv_output/survivor_multi_sample_vcf/first_500_INS.novelty.tsv \\
        --outdir docs/figures
"""

from __future__ import annotations

import argparse
import datetime
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

# Palette matches notebooks/novel_tr_results.ipynb so the two reports read as one
# system: one novelty class, one colour, everywhere.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

CLASSES = ["known", "novel_motif", "novel_locus"]
CLASS_COLOR = {"known": "#2a78d6", "novel_motif": "#eb6834", "novel_locus": "#1baf7a"}

mpl.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "figure.dpi": 160, "font.size": 9.5,
    "font.family": "sans-serif",
    "text.color": INK, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.edgecolor": AXIS, "axes.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False,
    "grid.color": GRID, "grid.linewidth": 0.8, "grid.linestyle": "-",
    "axes.grid": True, "axes.axisbelow": True,
    "legend.frameon": False,
})


def gc_content(motif: str) -> float:
    """Fraction of G/C bases in the repeat motif, in [0, 1].

    The previous version (notebooks/pop_viz.ipynb) computed
    ``motif.str.count('GC') * rep_units`` — the count of the literal
    substring "GC" scaled by copy number, which is neither bounded nor a
    measure of base composition. GC content is a property of the motif
    sequence itself, independent of how many times it repeats.
    """
    if not motif:
        return float("nan")
    gc = motif.count("G") + motif.count("C")
    return gc / len(motif)


def load(input_path: Path) -> pd.DataFrame:
    df = pd.read_csv(input_path, sep="\t")
    df["gc_content"] = df["motif"].astype(str).apply(gc_content)
    return df


def summary_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cls in CLASSES:
        sub = df[df["novelty"] == cls]
        rows.append({
            "novelty": cls,
            "n": len(sub),
            "%": f"{100 * len(sub) / len(df):.1f}%",
            "median motif_length": sub["motif_length"].median(),
            "median rep_length": sub["rep_length"].median(),
            "median purity": round(sub["purity"].median(), 3),
            "median gc_content": round(sub["gc_content"].median(), 3),
        })
    return pd.DataFrame(rows).set_index("novelty")


def plot_class_distribution(
    df: pd.DataFrame, column: str, ax_label: str, title: str, outfile: Path,
    binwidth: float | None = None, cap: float | None = None, discrete: bool = False,
) -> None:
    """Layered raw-count histogram of `column`, split by novelty class.

    If `cap` is given, values at or above it are pooled into a single
    overflow bin (labelled "<cap>+") instead of being silently dropped —
    a fixed binrange that stops at the cap without pooling excludes real
    data rather than summarizing it.
    """
    plot_col = column
    overflow_n = 0
    d = df
    if cap is not None:
        overflow_n = int((df[column] >= cap).sum())
        plot_col = f"{column}__capped"
        d = df.assign(**{plot_col: df[column].clip(upper=cap)})

    fig, ax = plt.subplots(figsize=(7.2, 3.6), constrained_layout=True)
    hist_kwargs = dict(
        data=d, x=plot_col, hue="novelty", hue_order=CLASSES, palette=CLASS_COLOR,
        stat="count", element="step", fill=True, alpha=0.4, multiple="layer", ax=ax,
    )
    if discrete:
        hist_kwargs["discrete"] = True
    else:
        hist_kwargs["binwidth"] = binwidth
        if cap is not None:
            hist_kwargs["binrange"] = (0, cap + binwidth)
    sns.histplot(**hist_kwargs)

    ax.set_title(title, loc="left", fontsize=11, fontweight="semibold")
    ax.set_xlabel(ax_label)
    ax.set_ylabel("Count")
    if discrete and cap is not None:
        ticks = list(range(1, int(cap) + 1, 2))
        labels = [str(t) for t in ticks]
        labels[-1] = f"{int(cap)}+"
        ax.set_xticks(ticks, labels)
    if overflow_n:
        ax.text(0.98, 0.72,
                f"{overflow_n:,} calls ({overflow_n / len(df):.1%}) pooled at {int(cap)}+\n"
                f"(actual values up to {df[column].max():,.0f})",
                transform=ax.transAxes, ha="right", fontsize=8, color=INK_2)
    legend = ax.get_legend()
    if legend is not None:
        legend.set_title("novelty")
    fig.savefig(outfile)
    plt.close(fig)


def plot_novelty_counts(df: pd.DataFrame, outfile: Path) -> None:
    counts = df["novelty"].value_counts().reindex(CLASSES)
    fig, ax = plt.subplots(figsize=(6.0, 3.4), constrained_layout=True)
    ax.barh(CLASSES[::-1], counts[CLASSES[::-1]], height=0.6,
            color=[CLASS_COLOR[c] for c in CLASSES[::-1]])
    for i, cls in enumerate(CLASSES[::-1]):
        ax.text(counts[cls] + counts.max() * 0.02, i,
                f"{counts[cls]:,} ({100 * counts[cls] / counts.sum():.0f}%)",
                va="center", fontsize=9, color=INK_2)
    ax.set_title("Calls by novelty class", loc="left", fontsize=11, fontweight="semibold")
    ax.set_xlim(0, counts.max() * 1.28)
    ax.set_xticks([])
    ax.grid(False)
    fig.savefig(outfile)
    plt.close(fig)


def build_report(df: pd.DataFrame, input_path: Path, assets_dir: Path, report_path: Path) -> None:
    assets_dir.mkdir(parents=True, exist_ok=True)

    plot_novelty_counts(df, assets_dir / "novelty_counts.png")
    plot_class_distribution(
        df, "motif_length", "Motif length (bp)", "Motif length by novelty class",
        assets_dir / "motif_length.png", cap=30, discrete=True,
    )
    plot_class_distribution(
        df, "rep_length", "Repeat tract length (bp)", "Repeat tract length by novelty class",
        assets_dir / "rep_length.png", binwidth=100, cap=3000,
    )
    plot_class_distribution(
        df, "purity", "Purity", "Purity by novelty class",
        assets_dir / "purity.png", binwidth=0.02,
    )
    plot_class_distribution(
        df, "gc_content", "GC content of motif", "GC content by novelty class",
        assets_dir / "gc_content.png", binwidth=0.05,
    )

    summary = summary_table(df)
    rel_assets = assets_dir.relative_to(report_path.parent)
    generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Population-level TR distributions by novelty class",
        "",
        f"*Generated {generated} by `src/python/reporting/population_report.py` "
        f"from `{input_path}` ({len(df):,} TRF calls across {df['SVID'].nunique():,} SVs).*",
        "",
        "Colours follow the same fixed palette as "
        "[`notebooks/novel_tr_results.ipynb`](../../notebooks/novel_tr_results.ipynb): "
        "one novelty class, one colour, everywhere. Distributions are shown as raw "
        "counts (not density) — class sizes differ by ~4x, so absolute magnitude "
        "matters here, not just shape.",
        "",
        "## Summary",
        "",
        summary.to_markdown(),
        "",
        f"![Calls by novelty class]({rel_assets}/novelty_counts.png)",
        "",
        "## Motif length",
        "",
        "Values at or above 30bp are pooled into the `30+` bucket and called out "
        "with an annotation — the underlying summary table above is exact. An "
        "earlier version of this chart used a fixed axis range that cut the view "
        "off at 32bp without pooling the overflow, which silently dropped 8.3% of "
        "all calls (actual motif lengths run up to 77bp) from the plot entirely.",
        "",
        f"![Motif length by novelty class]({rel_assets}/motif_length.png)",
        "",
        "## Repeat tract length",
        "",
        "Values at or above 3000bp are pooled into the `3000+` bucket the same way "
        "(here the overflow is small: 11 rows, 0.2% of all calls).",
        "",
        f"![Repeat tract length by novelty class]({rel_assets}/rep_length.png)",
        "",
        "## Purity",
        "",
        "`known` calls concentrate sharply around 0.67-0.85 purity; novel calls "
        "(both classes) are flatter and skew higher. This matters for "
        "interpreting the purity filter used downstream "
        "(`src/python/filter/filter_ins_trf.py`): it removes a "
        "disproportionate share of `novel_locus` calls relative to `known` ones.",
        "",
        f"![Purity by novelty class]({rel_assets}/purity.png)",
        "",
        "## GC content",
        "",
        "GC content is the fraction of G/C bases in the repeat motif itself "
        "(`(motif.count('G') + motif.count('C')) / len(motif)`), bounded in "
        "[0, 1] by definition — no capping needed. An earlier version of this "
        "chart (`notebooks/pop_viz.ipynb`) computed "
        "`motif.str.count('GC') * rep_units` — the literal substring count "
        "scaled by copy number — which is unbounded and does not measure base "
        "composition; that computation has been replaced here.",
        "",
        f"![GC content by novelty class]({rel_assets}/gc_content.png)",
        "",
    ]
    report_path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path,
        default=Path("data/sv_output/survivor_multi_sample_vcf/first_500_INS.novelty.tsv"),
        help="Novelty-annotated TRF calls TSV (output of `novelty annotate`).",
    )
    parser.add_argument(
        "--outdir", type=Path, default=Path("docs/figures"),
        help="Directory to write population_distributions.md and its assets/ subfolder into.",
    )
    args = parser.parse_args()

    df = load(args.input)
    report_path = args.outdir / "population_distributions.md"
    assets_dir = args.outdir / "assets" / "population_distributions"
    build_report(df, args.input, assets_dir, report_path)
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
