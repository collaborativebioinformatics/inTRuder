"""``analysis-reduce`` -- project one embedding view down to a few dimensions.

    analysis-reduce run.npz --layer blocks.26 --segment junction_5p \
        --method umap --out coords.tsv --plot umap.png --colour-by sample

The output is a TSV of the design frame with ``comp1..compN`` appended, so it
joins straight back onto anything keyed on ``row`` and is what
``analysis-cluster --coords`` consumes.

Three flags do most of the work:

``--delta --background ref.npz``
    subtract the reference allele at each breakpoint. Without this, a flank
    segment reproduces the locus and a junction segment is still anchored to it.
``--report confounds.tsv``
    score every component against insertion length, locus, sample and cropping.
    Run it every time; a component that is 90% length is not a finding.
``--grid grid.tsv``
    skip the projection and instead score all 45 (layer, segment) views, which
    is how you choose ``--layer``/``--segment`` on evidence rather than on the
    block-type argument in ``evo.embeddings.extract``.
"""

from __future__ import annotations

import argparse
import sys

from analysis.diagnostics import confound_report, neighbor_purity, view_grid
from analysis.dim_reduc.reduce import METHODS, reduce
from analysis.inputs import (
    add_view_arguments,
    describe,
    load_view,
    write_table,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="analysis-reduce",
        description="Reduce an Evo 2 embedding view to a few dimensions.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_view_arguments(p)

    g = p.add_argument_group("method")
    g.add_argument("--method", default="umap", choices=METHODS)
    g.add_argument("--components", type=int, default=2,
                   help="output dimensions")
    g.add_argument("--neighbors", type=int, default=15,
                   help="UMAP n_neighbors: the scale structure is kept at")
    g.add_argument("--min-dist", type=float, default=0.1,
                   help="UMAP min_dist: how tightly points may pack")
    g.add_argument("--perplexity", type=float, default=30.0,
                   help="t-SNE perplexity")
    g.add_argument("--metric", default="cosine",
                   help="neighbour metric for UMAP/t-SNE")
    g.add_argument("--pca-init", type=int, default=50,
                   help="PCA dimensions to build the neighbour graph in; 0 to "
                        "use the full space")
    g.add_argument("--seed", type=int, default=0)

    g = p.add_argument_group("output")
    g.add_argument("--out", default="-", help="coordinates TSV; - for stdout")
    g.add_argument("--report", help="write the confound report here")
    g.add_argument("--grid", nargs="?", const="-", metavar="TSV",
                   help="score every (layer, segment) view and exit")
    g.add_argument("--plot", help="write a scatter PNG here")
    g.add_argument("--colour-by", "--color-by", dest="colour_by", default="locus",
                   help="design column to colour the scatter by")
    g.add_argument("--quiet", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a, file=sys.stderr))

    if args.list:
        return describe(args)

    if args.grid:
        # The grid scores every view, so it deliberately skips load_view -- there
        # is no single layer or segment to select, and no delta to take.
        from analysis.matrix import design, load_runs

        emb = load_runs(args.npz)
        log("scoring every (layer, segment) view ...")
        table = view_grid(emb, design(emb), strand=args.strand,
                          normalize=args.normalize, metric=args.metric)
        write_table(table.sort_values("locus_excess"), args.grid, log)
        return 0

    X, frame, label = load_view(args, log)
    if len(X) < 3:
        raise SystemExit(f"only {len(X)} windows survive; nothing to reduce")

    log(f"{args.method} -> {args.components}d ...")
    result = reduce(
        X,
        method=args.method,
        n_components=args.components,
        n_neighbors=args.neighbors,
        min_dist=args.min_dist,
        perplexity=args.perplexity,
        metric=args.metric,
        pca_init=args.pca_init,
        seed=args.seed,
    )
    if result.explained_variance_ratio is not None:
        kept = result.explained_variance_ratio
        log(f"  variance kept: {kept.sum():.1%} "
            f"(comp1 {kept[0]:.1%}" + (f", comp2 {kept[1]:.1%}" if len(kept) > 1 else "")
            + ")")

    coords = result.frame()
    out = frame.join(coords)
    for key, value in result.params.items():
        out.attrs[key] = value
    write_table(out, args.out, log)

    purity = neighbor_purity(X, frame, k=min(10, len(X) - 1), metric=args.metric)
    if not purity.empty:
        log("neighbour purity in the input space "
            "(purity vs chance; high locus purity = you found the flanks):")
        for row in purity.itertuples():
            log(f"  {row.label:8s} {row.purity:.3f} vs {row.baseline:.3f} "
                f"chance   excess {row.excess:+.3f}")

    report = confound_report(result.coords, frame)
    if not report.empty:
        top = report.sort_values("abs_value", ascending=False).head(6)
        log("what the components track (strongest first, bias-corrected):")
        for row in top.itertuples():
            extra = ("" if row.kind == "continuous"
                     else f" (raw eta_sq {row.value:.3f}, {row.n_groups} groups)")
            shown = row.value if row.kind == "continuous" else row.adjusted
            name = row.statistic if row.kind == "continuous" else "epsilon_sq"
            log(f"  comp{row.component} ~ {row.covariate:14s} "
                f"{name} {shown:+.3f}{extra}")
        if args.report:
            write_table(report, args.report, log)

    if args.plot:
        from analysis.plotting import scatter

        scatter(result.coords, frame, args.colour_by,
                title=f"{result.method}: {label}", path=args.plot)
        log(f"wrote {args.plot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
