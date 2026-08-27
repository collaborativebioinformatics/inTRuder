"""Reduction, the diagnostics that qualify it, and the `analysis-reduce` CLI."""

from __future__ import annotations

import numpy as np
import pytest

from analysis.diagnostics import (
    confound_report,
    epsilon_squared,
    eta_squared,
    neighbor_purity,
    view_grid,
)
from analysis.dim_reduc.cli import main
from analysis.dim_reduc.reduce import reduce
from analysis.matrix import design, prepare, view

# --- reduce --------------------------------------------------------------------

def test_pca_reports_what_it_kept(run):
    X = prepare(view(run, "blocks.26", "junction_5p"), "l2")
    result = reduce(X, "pca", n_components=3)
    assert result.coords.shape == (len(X), 3)
    assert result.explained_variance_ratio is not None
    assert 0 < result.explained_variance_ratio.sum() <= 1.0


def test_umap_and_tsne_report_no_explained_variance(run):
    """They have no such quantity; offering one would invite reading their axes
    as if they were scaled."""
    X = prepare(view(run, "blocks.26", "junction_5p"), "l2")
    for method in ("umap", "tsne"):
        assert reduce(X, method, n_components=2).explained_variance_ratio is None


def test_umap_is_reproducible_under_a_seed(run):
    X = prepare(view(run, "blocks.26", "junction_5p"), "l2")
    a = reduce(X, "umap", seed=7)
    b = reduce(X, "umap", seed=7)
    assert np.allclose(a.coords, b.coords)


def test_params_travel_with_the_coordinates(run):
    X = prepare(view(run, "blocks.26", "junction_5p"), "l2")
    result = reduce(X, "umap", n_neighbors=4, min_dist=0.3, seed=3)
    assert result.params["n_neighbors"] == 4
    assert result.params["min_dist"] == 0.3
    assert result.params["seed"] == 3


def test_settings_are_clamped_to_what_the_data_allows(run):
    """n_neighbors above the row count is a crash in umap-learn, and a shard
    that came back small should not take the run down with it."""
    X = prepare(view(run, "blocks.26", "junction_5p"), "l2")[:6]
    assert reduce(X, "umap", n_neighbors=500).params["n_neighbors"] < 6
    assert reduce(X, "tsne", perplexity=500).params["perplexity"] < 6


def test_an_unknown_method_is_refused():
    with pytest.raises(ValueError, match="method must be one of"):
        reduce(np.zeros((5, 3), dtype=np.float32), "isomap")


# --- diagnostics ---------------------------------------------------------------

def test_eta_squared_is_one_when_the_group_is_the_value():
    values = np.array([1.0, 1.0, 5.0, 5.0])
    assert eta_squared(values, np.array(["a", "a", "b", "b"])) == pytest.approx(1.0)


def test_eta_squared_is_zero_when_the_group_says_nothing():
    values = np.array([1.0, 5.0, 1.0, 5.0])
    assert eta_squared(values, np.array(["a", "a", "b", "b"])) == pytest.approx(0.0)


def test_eta_squared_declines_a_question_with_no_answer():
    """One group, or as many groups as points -- 0 and 1 by arithmetic, not by
    data, and reporting them as findings would be a lie."""
    assert eta_squared(np.array([1.0, 2.0]), np.array(["a", "a"])) is None
    assert eta_squared(np.array([1.0, 2.0]), np.array(["a", "b"])) is None


def test_the_flank_segment_is_caught_as_a_locus_axis(run):
    """The check the module exists for: reduce a pure-flank view and the report
    must say the components are locus, at close to eta_sq 1."""
    X = prepare(view(run, "blocks.26", "left"), "l2")
    coords = reduce(X, "pca", n_components=2).coords
    report = confound_report(coords, design(run))
    locus = report[(report.covariate == "locus") & (report.component == 1)]
    assert float(locus["value"].iloc[0]) > 0.95


def test_the_report_refuses_a_mismatched_design(run):
    coords = np.zeros((3, 2))
    with pytest.raises(ValueError, match="subset the design"):
        confound_report(coords, design(run))


def test_neighbor_purity_separates_flank_from_junction(run):
    frame = design(run)
    flank = neighbor_purity(prepare(view(run, "blocks.26", "left"), "l2"), frame, k=3)
    junction = neighbor_purity(
        prepare(view(run, "blocks.26", "junction_5p"), "l2"), frame, k=3
    )
    locus = lambda f: float(f.set_index("label").loc["locus", "purity"])
    assert locus(flank) > 0.99          # the flanks *are* the locus
    assert locus(junction) < locus(flank)


def test_purity_is_reported_against_chance(run):
    """With 6 loci x 5 samples, a random neighbour shares a locus 14% of the
    time. A bare purity of 0.2 would look like nothing and be above chance."""
    frame = design(run)
    out = neighbor_purity(prepare(view(run, "blocks.26", "left"), "l2"), frame, k=3)
    row = out.set_index("label").loc["locus"]
    assert row["baseline"] == pytest.approx(4 / 29, abs=1e-3)
    assert row["excess"] == pytest.approx(row["purity"] - row["baseline"])


def test_the_grid_skips_overflowed_layers_rather_than_zeroing_them(run):
    grid = view_grid(run, design(run), k=3)
    assert len(grid) == len(run.layers) * len(run.segments)
    bad = grid[grid.layer == "blocks.31"]
    assert (bad["status"] == "nonfinite").all()
    assert bad["locus_purity"].isna().all()


def test_the_grid_ranks_junction_below_flank_on_locus_purity(run):
    """What the grid is for: choosing a view on evidence. The junction segment
    must look less like a locus lookup than the flank does."""
    grid = view_grid(run, design(run), layers=["blocks.26"], k=3).set_index("segment")
    assert grid.loc["junction_5p", "locus_excess"] < grid.loc["left", "locus_excess"]


# --- CLI -----------------------------------------------------------------------

def test_cli_writes_coordinates_joined_to_the_design(npz, tmp_path, capsys):
    out = tmp_path / "coords.tsv"
    assert main([npz, "--layer", "blocks.26", "--segment", "junction_5p",
                 "--method", "pca", "--out", str(out), "--quiet"]) == 0
    header = out.read_text().splitlines()[0].split("\t")
    assert "comp1" in header and "comp2" in header
    assert "locus" in header and "row" in header


def test_cli_defaults_to_a_layer_that_survived_float16(npz, tmp_path):
    """No --layer given: it must not pick blocks.31 and produce NaN."""
    out = tmp_path / "coords.tsv"
    assert main([npz, "--method", "pca", "--out", str(out), "--quiet"]) == 0
    assert "nan" not in out.read_text().lower()


def test_cli_refuses_the_overflowed_layer_when_asked_for_it(npz, tmp_path):
    with pytest.raises(ValueError, match="inf or NaN"):
        main([npz, "--layer", "blocks.31", "--method", "pca",
              "--out", str(tmp_path / "c.tsv"), "--quiet"])


def test_cli_delta_needs_a_background(npz, tmp_path):
    with pytest.raises(SystemExit, match="--delta needs --background"):
        main([npz, "--delta", "--method", "pca",
              "--out", str(tmp_path / "c.tsv"), "--quiet"])


def test_cli_delta_subtracts_the_background(npz, background_npz, tmp_path):
    out = tmp_path / "coords.tsv"
    assert main([npz, "--background", background_npz, "--delta",
                 "--layer", "blocks.26", "--segment", "junction_5p",
                 "--method", "pca", "--out", str(out), "--quiet"]) == 0
    assert len(out.read_text().splitlines()) == 31  # 30 windows + header


def test_cli_grid_scores_every_view(npz, tmp_path):
    out = tmp_path / "grid.tsv"
    assert main([npz, "--grid", str(out), "--quiet"]) == 0
    text = out.read_text()
    assert "nonfinite" in text
    assert "junction_5p" in text


def test_cli_list_describes_the_run(npz, capsys):
    assert main([npz, "--list"]) == 0
    printed = capsys.readouterr().out
    assert "blocks.31" in printed and "NONFINITE" in printed
    assert "loci: 6" in printed


def test_cli_writes_a_plot(npz, tmp_path):
    plot = tmp_path / "umap.png"
    assert main([npz, "--method", "pca", "--out", str(tmp_path / "c.tsv"),
                 "--plot", str(plot), "--colour-by", "locus", "--quiet"]) == 0
    assert plot.stat().st_size > 0


def test_cli_names_the_segments_that_exist(npz, tmp_path):
    with pytest.raises(SystemExit, match="junction_5p"):
        main([npz, "--segment", "exon", "--out", str(tmp_path / "c.tsv"), "--quiet"])


def test_epsilon_squared_is_zero_for_a_random_split():
    """The correction that matters: 65 groups over 100 points explains ~65% of
    pure noise on the raw scale and nothing at all on this one."""
    rng = np.random.default_rng(0)
    values = rng.normal(size=100)
    groups = np.repeat(np.arange(50), 2).astype(str)
    assert eta_squared(values, groups) > 0.4
    assert abs(epsilon_squared(values, groups)) < 0.35


def test_epsilon_squared_goes_negative_below_chance():
    values = np.array([0.0, 10.0, 0.0, 10.0, 0.0, 10.0])
    groups = np.array(["a", "a", "b", "b", "c", "c"])
    assert epsilon_squared(values, groups) < 0


def test_epsilon_squared_keeps_a_real_effect():
    values = np.array([1.0, 1.1, 9.0, 9.1, 1.0, 1.2, 9.2, 9.0])
    groups = np.array(["a", "a", "b", "b", "a", "a", "b", "b"])
    assert epsilon_squared(values, groups) > 0.95


def test_the_report_carries_both_scales(run):
    X = prepare(view(run, "blocks.26", "left"), "l2")
    coords = reduce(X, "pca", n_components=2).coords
    report = confound_report(coords, design(run))
    categorical = report[report.kind == "categorical"]
    assert categorical["adjusted"].notna().all()
    assert (categorical["adjusted"] <= categorical["value"] + 1e-9).all()
