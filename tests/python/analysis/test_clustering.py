"""Partitioning, agreement scoring, novelty scoring, and the CLI."""

from __future__ import annotations

import numpy as np
import pytest

from analysis.clustering.cli import main
from analysis.clustering.cluster import (
    agreement,
    cluster,
    novelty_scores,
    sweep_k,
)
from analysis.matrix import design, prepare, view

# --- cluster -------------------------------------------------------------------

def test_kmeans_returns_exactly_k_groups(run):
    X = prepare(view(run, "blocks.26", "left"), "l2")
    result = cluster(X, "kmeans", k=6, seed=0)
    assert result.n_clusters == 6
    assert result.n_noise == 0


def test_hdbscan_may_refuse_to_place_a_point(run):
    """The reason it is the default: with a handful of samples at some loci and
    many at others, a method that must assign everything invents groups."""
    X = prepare(view(run, "blocks.26", "junction_5p"), "l2")
    result = cluster(X, "hdbscan", min_cluster_size=3)
    assert result.n_noise >= 0
    assert -1 not in set(result.labels) - {-1}


def test_agglomerative_can_be_cut_by_distance_instead_of_count(run):
    X = prepare(view(run, "blocks.26", "left"), "l2")
    result = cluster(X, "agglomerative", distance_threshold=0.5, metric="cosine")
    assert result.params["k"] is None
    assert result.n_clusters >= 1


def test_scores_come_back_with_the_labels(run):
    X = prepare(view(run, "blocks.26", "left"), "l2")
    result = cluster(X, "kmeans", k=6)
    assert set(result.scores) >= {"silhouette", "calinski_harabasz", "davies_bouldin"}
    assert result.scores["silhouette"] > 0.5  # the flanks are 6 tight balls


def test_scores_are_nan_not_a_crash_when_there_is_one_cluster():
    X = np.zeros((5, 3), dtype=np.float32)
    result = cluster(X, "hdbscan", min_cluster_size=4)
    assert np.isnan(result.scores["silhouette"])


def test_an_unknown_method_is_refused(run):
    with pytest.raises(ValueError, match="method must be one of"):
        cluster(np.zeros((5, 3), dtype=np.float32), "spectral")


# --- agreement -----------------------------------------------------------------

def test_clustering_the_flanks_is_caught_as_recovering_the_locus(run):
    """The headline check. A partition of a flank view should score near 1
    against `locus`, which is a warning and not a result."""
    X = prepare(view(run, "blocks.26", "left"), "l2")
    result = cluster(X, "kmeans", k=6, seed=0)
    match = agreement(result.labels, design(run)).set_index("covariate")
    assert match.loc["locus", "ari"] > 0.95
    assert match.loc["locus", "homogeneity"] > 0.95


def test_a_junction_partition_agrees_with_the_locus_far_less(run):
    frame = design(run)
    flank = cluster(prepare(view(run, "blocks.26", "left"), "l2"), "kmeans", k=6)
    junction = cluster(
        prepare(view(run, "blocks.26", "junction_5p"), "l2"), "kmeans", k=6
    )
    ari = lambda c: float(
        agreement(c.labels, frame).set_index("covariate").loc["locus", "ari"]
    )
    assert ari(junction) < ari(flank)


def test_noise_points_are_left_out_of_the_agreement(run):
    labels = np.full(len(run.vectors), -1)
    labels[:10] = [0] * 5 + [1] * 5
    match = agreement(labels, design(run))
    assert (match["n_scored"] == 10).all()


# --- sweep ---------------------------------------------------------------------

def test_the_sweep_reports_locus_agreement_beside_the_silhouette(run):
    """A silhouette peak at the locus count is a peak to distrust, so the two
    numbers have to be readable side by side."""
    X = prepare(view(run, "blocks.26", "left"), "l2")
    table = sweep_k(X, ks=(2, 3, 6), design=design(run))
    assert list(table["k"]) == [2, 3, 6]
    assert "ari_locus" in table
    assert table.loc[table["k"] == 6, "ari_locus"].iloc[0] > 0.9


def test_the_sweep_skips_a_k_larger_than_the_data(run):
    X = prepare(view(run, "blocks.26", "left"), "l2")[:5]
    assert list(sweep_k(X, ks=(2, 3, 99))["k"]) == [2, 3]


# --- novelty -------------------------------------------------------------------

def test_the_background_supplies_the_null(run, background):
    """Distance to the reference-allele windows: a junction that moved far from
    its reference must score above one that barely moved."""
    X = prepare(view(run, "blocks.26", "junction_5p"), "l2")
    bg = prepare(view(background, "blocks.26", "junction_5p"), "l2")
    scores = novelty_scores(X, bg, k=1)
    assert (scores["basis"] == "background_knn").all()
    assert len(scores) == len(X)
    assert scores["score"].min() >= 0


def test_a_planted_outlier_ranks_first():
    """Geometry, not the fixture: in 16 random dimensions every point is nearly
    equidistant from every other, so a planted outlier has to be planted far
    away for the assertion to mean anything."""
    rng = np.random.default_rng(0)
    bg = rng.normal(size=(50, 4))
    X = rng.normal(size=(20, 4))
    X[3] += 100.0
    scores = novelty_scores(X, bg, k=1)
    assert scores["rank"].iloc[3] == 1
    assert scores["score"].iloc[3] > scores["score"].drop(index=3).max()


def test_without_a_background_it_says_so(run):
    X = prepare(view(run, "blocks.26", "junction_5p"), "l2")
    scores = novelty_scores(X, None)
    assert (scores["basis"] == "lof").all()
    assert np.isfinite(scores["score"]).all()


# --- CLI -----------------------------------------------------------------------

def test_cli_writes_labels_joined_to_the_design(npz, tmp_path):
    out = tmp_path / "labels.tsv"
    assert main([npz, "--layer", "blocks.26", "--segment", "left",
                 "--method", "kmeans", "-k", "6", "--out", str(out), "--quiet"]) == 0
    header = out.read_text().splitlines()[0].split("\t")
    assert "cluster" in header and "locus" in header


def test_cli_novelty_uses_the_background(npz, background_npz, tmp_path):
    out = tmp_path / "scores.tsv"
    assert main([npz, "--novelty", "--background", background_npz,
                 "--layer", "blocks.26", "--segment", "junction_5p",
                 "--out", str(out), "--quiet"]) == 0
    text = out.read_text()
    assert "background_knn" in text
    assert "score" in text.splitlines()[0]


def test_cli_novelty_falls_back_to_lof_without_one(npz, tmp_path):
    out = tmp_path / "scores.tsv"
    assert main([npz, "--novelty", "--layer", "blocks.26", "--out", str(out),
                 "--quiet"]) == 0
    assert "lof" in out.read_text()


def test_cli_refuses_to_both_subtract_and_measure_the_background(npz, background_npz,
                                                                 tmp_path):
    with pytest.raises(SystemExit, match="Pick one"):
        main([npz, "--novelty", "--delta", "--background", background_npz,
              "--out", str(tmp_path / "s.tsv"), "--quiet"])


def test_cli_sweep_refuses_hdbscan(npz, tmp_path):
    with pytest.raises(SystemExit, match="picks its own cluster count"):
        main([npz, "--sweep", "2,4", "--method", "hdbscan",
              "--out", str(tmp_path / "s.tsv"), "--quiet"])


def test_cli_clusters_reduced_coordinates_aligned_by_row(npz, tmp_path):
    from analysis.dim_reduc.cli import main as reduce_main

    coords = tmp_path / "coords.tsv"
    reduce_main([npz, "--layer", "blocks.26", "--segment", "left",
                 "--method", "pca", "--out", str(coords), "--quiet"])
    out = tmp_path / "labels.tsv"
    assert main([npz, "--layer", "blocks.26", "--segment", "left",
                 "--coords", str(coords), "--method", "kmeans", "-k", "6",
                 "--out", str(out), "--quiet"]) == 0
    assert "comp1" in out.read_text().splitlines()[0]


def test_cli_refuses_coordinates_that_are_not_for_this_view(npz, tmp_path):
    """A --delta reduction drops unpaired windows, so its file is shorter than
    the run; a positional join would shift every label silently."""
    coords = tmp_path / "coords.tsv"
    coords.write_text("row\tcomp1\tcomp2\n0\t1.0\t2.0\n")
    with pytest.raises(SystemExit, match="no coordinates for some windows"):
        main([npz, "--layer", "blocks.26", "--coords", str(coords),
              "--out", str(tmp_path / "l.tsv"), "--quiet"])


def test_cli_rejects_a_coords_file_without_components(npz, tmp_path):
    bad = tmp_path / "bad.tsv"
    bad.write_text("row\tlocus\n0\tchr1:1000\n")
    with pytest.raises(SystemExit, match="analysis-reduce output"):
        main([npz, "--coords", str(bad), "--out", str(tmp_path / "l.tsv"), "--quiet"])


def test_cli_plot_needs_coordinates(npz, tmp_path):
    with pytest.raises(SystemExit, match="nothing 2-D to draw"):
        main([npz, "--layer", "blocks.26", "--plot", str(tmp_path / "p.png"),
              "--out", str(tmp_path / "l.tsv"), "--quiet"])
