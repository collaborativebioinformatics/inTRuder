"""Generate a Markdown QC report of insertions carried per genome, by ancestry.

Two views of the same 67 HPRC genomes, using the same axis, order, and colour
so they can be compared directly:

  1. Raw non-reference insertion calls (the merged Sniffles2/SURVIVOR VCF),
     before any TR annotation.
  2. TR-spanning insertion calls (this repo's `sv_trfcaller` + `novelty`
     output) -- the pipeline's own output.

Both source files are large per-sample VCF/TSV dumps that are not checked
into this repo; point --multisample-tsv and --raw-vcf at your own copies.
This script writes the small (67-row) derived per-sample counts to
data/ancestry/insertions_per_sample.tsv so the report can be regenerated
without re-parsing the large inputs.

Usage:
    python src/python/reporting/ancestry_report.py \\
        --multisample-tsv /path/to/05_hprc_multisample.tsv \\
        --raw-vcf /path/to/hprc_multisample.INS_comp.vcf \\
        --ancestry data/ancestry/HPRC_samples_ancestry.tsv \\
        --outdir docs/visualizations
"""

from __future__ import annotations

import argparse
import datetime
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
BLUE = "#2a78d6"

# Fixed order (not sorted by mean) so the raw and TR-spanning plots line up
# for direct visual comparison.
SUPERPOP_ORDER = ["AFR", "AMR", "EUR", "SAS", "EAS"]

mpl.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "figure.dpi": 160, "font.size": 10, "font.family": "sans-serif",
    "text.color": INK, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.edgecolor": AXIS, "axes.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.bottom": False,
    "grid.color": GRID, "grid.linewidth": 0.8, "grid.linestyle": "-",
    "axes.grid": True, "axes.axisbelow": True, "legend.frameon": False,
})

NON_REF_GTS = {"0/1", "1/0", "1/1", "0|1", "1|0", "1|1"}


def count_raw_insertions_per_sample(vcf_path: Path) -> pd.DataFrame:
    """Count non-reference INS genotypes per sample in a merged VCF.

    Reads the FORMAT/GT field directly rather than pulling in a VCF library,
    since all we need is genotype presence/absence per sample per record.
    """
    samples: list[str] | None = None
    counts: list[int] = []
    with open(vcf_path) as f:
        for line in f:
            if line.startswith("##"):
                continue
            if line.startswith("#CHROM"):
                fields = line.rstrip("\n").split("\t")
                samples = fields[9:]
                counts = [0] * len(samples)
                continue
            fields = line.rstrip("\n").split("\t")
            if "SVTYPE=INS" not in fields[7]:
                continue
            for i, cell in enumerate(fields[9:]):
                if cell.split(":", 1)[0] in NON_REF_GTS:
                    counts[i] += 1
    if samples is None:
        raise ValueError(f"no #CHROM header found in {vcf_path}")
    return pd.DataFrame({"sample": samples, "n_insertions_raw": counts})


def count_tr_insertions_per_sample(tsv_path: Path) -> pd.DataFrame:
    """Count distinct TR-spanning insertions per sample in the pipeline output.

    `sv_trfcaller.py` currently double-emits every repeat call for
    homozygous-alt genotypes -- exact duplicate rows, not distinct repeat
    regions (see issue_duplicate_rows.md). Count distinct (sample, SVID)
    pairs, not raw rows, so hom-alt loci aren't counted twice.
    """
    calls = pd.read_csv(tsv_path, sep="\t", usecols=["SVID", "sample"])
    return (
        calls.drop_duplicates(["sample", "SVID"])
        .groupby("sample").size().rename("n_insertions_tr").reset_index()
    )


def build_per_sample_table(raw_vcf: Path, multisample_tsv: Path, ancestry_path: Path) -> pd.DataFrame:
    raw = count_raw_insertions_per_sample(raw_vcf)
    tr = count_tr_insertions_per_sample(multisample_tsv)
    anc = pd.read_csv(ancestry_path, sep="\t", header=None, names=["sample", "sex", "superpop"])
    df = anc.merge(raw, on="sample", how="inner").merge(tr, on="sample", how="inner")
    if len(df) != len(anc):
        missing = set(anc["sample"]) - set(df["sample"])
        raise ValueError(f"{len(missing)} ancestry samples missing from VCF/TSV: {sorted(missing)}")
    return df


def plot_swarm(df: pd.DataFrame, column: str, ylabel: str, title: str, subtitle: str, outfile: Path) -> None:
    order = [s for s in SUPERPOP_ORDER if s in df["superpop"].unique()]
    means = df.groupby("superpop")[column].mean()

    fig, ax = plt.subplots(figsize=(9.0, 6.4), constrained_layout=True)
    sns.swarmplot(data=df, x="superpop", y=column, order=order, color=BLUE,
                  size=6, alpha=0.85, ax=ax)

    yspan = df[column].max() - df[column].min()
    for i, s in enumerate(order):
        m = means[s]
        ax.plot([i - 0.22, i + 0.22], [m, m], color=INK, lw=2, zorder=5)
        ax.text(i, m + yspan * 0.035, f"{m:,.0f}", ha="center", va="bottom", fontsize=9.5, color=INK,
                bbox=dict(facecolor=SURFACE, edgecolor="none", pad=1.2, alpha=0.85), zorder=6)

    n_per_group = df.groupby("superpop").size()
    ax.set_xticks(range(len(order)), [f"{s}\nn={n_per_group[s]}" for s in order])
    ax.set_xlabel("1000 Genomes superpopulation")
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", fontsize=13, fontweight="semibold", pad=40)
    ax.text(0, 1.045, subtitle, transform=ax.transAxes, fontsize=9.5, color=INK_2, va="bottom")

    fig.savefig(outfile)
    plt.close(fig)


def build_report(df: pd.DataFrame, assets_dir: Path, report_path: Path,
                  raw_vcf: Path, multisample_tsv: Path) -> None:
    assets_dir.mkdir(parents=True, exist_ok=True)

    plot_swarm(
        df, "n_insertions_raw", "Non-reference insertions carried per genome",
        "Non-reference insertions carried per genome, by superpopulation",
        f"QC: one point per genome; {len(df):,} genomes, {df['n_insertions_raw'].sum():,} total non-reference "
        f"insertion calls.\nRaw Sniffles2/SURVIVOR calls, before TR annotation.",
        assets_dir / "insertions_raw.png",
    )
    plot_swarm(
        df, "n_insertions_tr", "TR-spanning insertions carried per genome",
        "TR-spanning insertions carried per genome, by superpopulation",
        f"QC: one point per genome; {len(df):,} genomes, {df['n_insertions_tr'].sum():,} total TR-spanning "
        f"insertion calls.\nAfter sv_trfcaller + novelty (this is the pipeline's output, not the raw VCF).",
        assets_dir / "insertions_tr.png",
    )

    summary = (
        df.groupby("superpop")[["n_insertions_raw", "n_insertions_tr"]]
        .agg(["count", "mean", "median"])
        .loc[[s for s in SUPERPOP_ORDER if s in df["superpop"].unique()]]
    )
    summary.columns = ["_".join(c) for c in summary.columns]
    summary = summary.rename(columns={"n_insertions_raw_count": "n_genomes"}).drop(
        columns=["n_insertions_tr_count"]
    )
    for c in summary.columns:
        if c != "n_genomes":
            summary[c] = summary[c].round(0).astype(int)

    rel_assets = assets_dir.relative_to(report_path.parent)
    generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Insertions carried per genome, by ancestry (QC)",
        "",
        f"*Generated {generated} by `src/python/reporting/ancestry_report.py` from "
        f"`{raw_vcf.name}` and `{multisample_tsv.name}` ({len(df)} HPRC genomes).*",
        "",
        "Descriptive QC only, no significance testing. Both plots share the same "
        "superpopulation order, axis style, and colour so they can be compared "
        "directly -- what changes between them is entirely due to the TR "
        "pipeline (`sv_trfcaller` + `novelty`), not a different cohort or axis.",
        "",
        "## Summary",
        "",
        summary.to_markdown(),
        "",
        "## Before the pipeline: raw insertion calls",
        "",
        "The full merged callset (`SVTYPE=INS`, non-reference genotype), independent "
        "of whether an insertion contains a tandem repeat.",
        "",
        f"![Raw insertions per genome by superpopulation]({rel_assets}/insertions_raw.png)",
        "",
        "## After the pipeline: TR-spanning insertion calls",
        "",
        "Same 67 genomes, counted from this repo's own output "
        "(`sv_trfcaller` + `novelty annotate`). Counted as distinct "
        "`(sample, SVID)` pairs rather than raw rows, since `sv_trfcaller.py` "
        "currently double-emits every repeat call for homozygous-alt genotypes "
        "(see `issue_duplicate_rows.md`) -- counting raw rows would overstate "
        "per-sample totals by ~36%.",
        "",
        f"![TR-spanning insertions per genome by superpopulation]({rel_assets}/insertions_tr.png)",
        "",
        "## What changes between the two",
        "",
        "Before the pipeline, AFR genomes clearly carry the most non-reference "
        "insertions of any group -- a well-known effect of calling structural "
        "variants against a reference genome that under-represents African "
        "genetic diversity. After restricting to TR-spanning insertions, that "
        "ordering changes (AMR leads on this smaller, noisier subset) and the "
        "gap narrows substantially. Whether that shift reflects something real "
        "about which insertions are TR-containing, or is just sampling noise on "
        "a ~15x smaller subset, isn't something this QC pass can answer -- it "
        "only establishes that the two views disagree and both denominators "
        "are needed to see it.",
        "",
    ]
    report_path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--multisample-tsv", type=Path, required=True,
                         help="Per-call TSV from sv_trfcaller + novelty annotate, e.g. 05_hprc_multisample.tsv")
    parser.add_argument("--raw-vcf", type=Path, required=True,
                         help="Merged multi-sample VCF before TR annotation, e.g. hprc_multisample.INS_comp.vcf")
    parser.add_argument("--ancestry", type=Path, default=Path("data/ancestry/HPRC_samples_ancestry.tsv"),
                         help="TSV: sample, sex, superpopulation (no header).")
    parser.add_argument("--outdir", type=Path, default=Path("docs/visualizations"))
    parser.add_argument("--per-sample-out", type=Path, default=Path("data/ancestry/insertions_per_sample.tsv"),
                         help="Where to write the small derived per-sample counts table.")
    args = parser.parse_args()

    df = build_per_sample_table(args.raw_vcf, args.multisample_tsv, args.ancestry)
    args.per_sample_out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.per_sample_out, sep="\t", index=False)
    print(f"Wrote {args.per_sample_out}")

    report_path = args.outdir / "ancestry_qc.md"
    assets_dir = args.outdir / "assets" / "ancestry_qc"
    build_report(df, assets_dir, report_path, args.raw_vcf, args.multisample_tsv)
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
