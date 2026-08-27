"""``analysis-cluster`` -- partition an embedding view, or score how novel it is.

    analysis-cluster run.npz --layer blocks.26 --segment junction_5p \
        --method hdbscan --out labels.tsv

    # the question the project is actually asking
    analysis-cluster run.npz --background ref.npz --novelty --out scores.tsv

Two modes. The default clusters and reports how much of the partition was
already predictable from ``locus``, ``sample``, ``chrom`` and ``cropped`` --
read that table before the cluster count, because a partition that recovers the
locus is the flanks and nothing more.

``--novelty`` skips clustering and scores each window against the
reference-allele background at the same breakpoints, which needs no cluster
boundaries and no choice of ``k``.

Clustering can run on the embedding view directly or, with ``--coords``, on the
output of ``analysis-reduce``. They answer different questions: the full space
is the honest one, while clustering 2-D UMAP coordinates finds the groups *UMAP
drew*, which is circular unless that is explicitly what you want.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from analysis.clustering.cluster import (
    METHODS,
    agreement,
    cluster,
    novelty_scores,
    sweep_k,
)
from analysis.inputs import add_view_arguments, describe, load_view, write_table


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="analysis-cluster",
        description="Cluster or novelty-score an Evo 2 embedding view.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_view_arguments(p)

    g = p.add_argument_group("method")
    g.add_argument("--method", default="hdbscan", choices=METHODS)
    g.add_argument("-k", "--clusters", type=int, default=8,
                   help="cluster count for kmeans/agglomerative")
    g.add_argument("--min-cluster-size", type=int, default=5,
                   help="HDBSCAN: smallest group that counts as a cluster")
    g.add_argument("--min-samples", type=int,
                   help="HDBSCAN: how conservative the density estimate is")
    g.add_argument("--linkage", default="average",
                   choices=("average", "complete", "single", "ward"),
                   help="agglomerative linkage")
    g.add_argument("--distance-threshold", type=float,
                   help="agglomerative: cut the tree here instead of at -k")
    g.add_argument("--cluster-metric", default="euclidean",
                   help="distance for HDBSCAN/agglomerative; with --normalize "
                        "l2, euclidean is cosine")
    g.add_argument("--seed", type=int, default=0)

    g = p.add_argument_group("mode")
    g.add_argument("--coords", metavar="TSV",
                   help="cluster these analysis-reduce coordinates instead of "
                        "the embedding view")
    g.add_argument("--sweep", metavar="KS",
                   help="comma-separated cluster counts to score, then exit")
    g.add_argument("--novelty", action="store_true",
                   help="score distance from the reference-allele background "
                        "instead of clustering")
    g.add_argument("--novelty-k", type=int, default=5,
                   help="which nearest background window sets the score")

    g = p.add_argument_group("output")
    g.add_argument("--out", default="-", help="TSV of labels or scores; - for stdout")
    g.add_argument("--agreement-out", help="write the agreement table here")
    g.add_argument("--plot", help="write a scatter PNG here; needs --coords")
    g.add_argument("--quiet", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a, file=sys.stderr))

    if args.list:
        return describe(args)

    if args.novelty:
        return _novelty(args, log)

    X, frame, label = load_view(args, log)
    coords = None
    if args.coords:
        coords, X = _read_coords(args.coords, frame)
        log(f"clustering {X.shape[1]} reduced dimensions from {args.coords}")

    if args.sweep:
        ks = [int(s) for s in args.sweep.split(",") if s.strip()]
        table = sweep_k(X, ks, method=_sweepable(args.method), design=frame,
                        seed=args.seed, metric=args.cluster_metric,
                        linkage=args.linkage)
        write_table(table, args.out, log)
        return 0

    result = cluster(
        X, method=args.method,
        k=args.clusters, seed=args.seed,
        min_cluster_size=args.min_cluster_size, min_samples=args.min_samples,
        linkage=args.linkage, distance_threshold=args.distance_threshold,
        metric=args.cluster_metric,
    )
    log(f"{result.method}: {result.n_clusters} clusters, "
        f"{result.n_noise} noise ({result.n_noise / len(X):.1%})")
    log("  " + "  ".join(f"{k} {v:.3f}" if isinstance(v, float) else f"{k} {v}"
                         for k, v in result.scores.items()))

    match = agreement(result.labels, frame)
    if not match.empty:
        log("agreement with what we already knew (high = not a new finding):")
        for row in match.itertuples():
            log(f"  {row.covariate:8s} ARI {row.ari:+.3f}  AMI {row.ami:+.3f}  "
                f"homogeneity {row.homogeneity:.3f}")
        if args.agreement_out:
            write_table(match, args.agreement_out, log)

    out = frame.copy()
    out["cluster"] = result.labels
    if coords is not None:
        out = out.join(coords)
    write_table(out, args.out, log)

    if args.plot:
        if coords is None:
            raise SystemExit("--plot needs --coords: there is nothing 2-D to draw")
        from analysis.plotting import scatter

        scatter(coords.to_numpy(), out, "cluster",
                title=f"{result.method}: {label}", path=args.plot)
        log(f"wrote {args.plot}")
    return 0


def _novelty(args: argparse.Namespace, log) -> int:
    """Score each insertion against the reference-allele background."""
    from analysis.matrix import design, finite_layers, load_runs, prepare, view

    if args.delta:
        raise SystemExit(
            "--novelty and --delta both use the background, differently: "
            "--delta subtracts it per breakpoint, --novelty measures distance "
            "to it. Pick one."
        )
    emb = load_runs(args.npz)
    layer = args.layer or (finite_layers(emb, args.segment) or [None])[0]
    if layer is None:
        raise SystemExit(f"no finite layer at segment {args.segment!r}")
    frame = design(emb)
    X = prepare(view(emb, layer, args.segment, args.strand, args.allow_nonfinite),
                args.normalize)

    background = None
    if args.background:
        bg = load_runs(args.background)
        background = prepare(
            view(bg, layer, args.segment, args.strand, args.allow_nonfinite),
            args.normalize,
        )
        log(f"background: {len(background)} reference-allele windows")
    else:
        log("no --background given; falling back to LOF within this run, which "
            "finds insertions unusual among insertions, not against the reference")

    scores = novelty_scores(X, background, k=args.novelty_k,
                            metric=args.cluster_metric)
    out = pd.concat([frame, scores], axis=1)
    top = out.nlargest(min(10, len(out)), "score")
    log(f"most unusual windows ({scores.loc[0, 'basis']}):")
    for row in top.itertuples():
        log(f"  {row.locus:<20s} {row.sample:<10s} len {row.insert_length:>6d}  "
            f"score {row.score:.4f}")
    write_table(out, args.out, log)
    return 0


def _read_coords(path: str, frame: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """The ``comp*`` columns of an analysis-reduce output, aligned by ``row``.

    Aligning on ``row`` rather than trusting file order is what makes it safe to
    reduce with ``--delta`` (which drops unpaired windows) and then cluster the
    result: the two files no longer have the same length, and a positional join
    would shift every label.
    """
    table = pd.read_csv(path, sep="\t")
    comps = [c for c in table.columns if c.startswith("comp")]
    if not comps:
        raise SystemExit(f"{path}: no comp1..compN columns; is it analysis-reduce output?")
    if "row" not in table.columns:
        raise SystemExit(f"{path}: no `row` column to align on")
    aligned = frame[["row"]].merge(table[["row", *comps]], on="row", how="left")
    if aligned[comps].isna().any().any():
        raise SystemExit(
            f"{path} has no coordinates for some windows in {frame['row'].size} "
            "rows; reduce and cluster the same view"
        )
    coords = aligned[comps].reset_index(drop=True)
    return coords, coords.to_numpy(dtype=float)


def _sweepable(method: str) -> str:
    """HDBSCAN chooses its own cluster count, so a k sweep is meaningless."""
    if method == "hdbscan":
        raise SystemExit("--sweep needs --method kmeans or agglomerative; "
                         "hdbscan picks its own cluster count")
    return method


if __name__ == "__main__":
    raise SystemExit(main())
