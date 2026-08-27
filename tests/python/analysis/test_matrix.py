"""View selection, sanitation, normalisation and the reference subtraction."""

from __future__ import annotations

import numpy as np
import pytest

from analysis.matrix import (
    background_index,
    delta,
    design,
    finite_layers,
    load_runs,
    prepare,
    view,
)

# --- finite_layers -------------------------------------------------------------

def test_the_overflowed_layer_is_excluded(run):
    assert finite_layers(run) == ["blocks.16", "blocks.26"]


def test_finiteness_can_be_asked_per_segment(run):
    assert "blocks.31" not in finite_layers(run, "junction_5p")


# --- view ----------------------------------------------------------------------

def test_a_nonfinite_layer_raises_rather_than_propagating(run):
    """The failure mode this guard exists for: an all-NaN UMAP with no error."""
    with pytest.raises(ValueError, match="inf or NaN"):
        view(run, "blocks.31", "junction_5p")


def test_nonfinite_can_be_zeroed_on_request(run):
    X = view(run, "blocks.31", "junction_5p", allow_nonfinite=True)
    assert np.isfinite(X).all()
    assert (X == 0).all()


def test_strand_halves_split_the_vector(run):
    both = view(run, "blocks.26", "junction_5p", "both")
    fwd = view(run, "blocks.26", "junction_5p", "forward")
    rev = view(run, "blocks.26", "junction_5p", "reverse")
    assert both.shape[1] == fwd.shape[1] + rev.shape[1]
    assert np.array_equal(both, np.hstack([fwd, rev]))


def test_output_is_float32_whatever_was_stored(run):
    assert view(run, "blocks.26", "left").dtype == np.float32


def test_an_unknown_layer_names_the_ones_that_exist(run):
    with pytest.raises(KeyError, match="blocks.16"):
        view(run, "blocks.99", "left")


# --- prepare -------------------------------------------------------------------

def test_l2_gives_unit_rows(run):
    X = prepare(view(run, "blocks.26", "junction_5p"), "l2")
    assert np.allclose(np.linalg.norm(X, axis=1), 1.0, atol=1e-5)


def test_l2_leaves_an_empty_segment_at_the_origin():
    """A `repeat` span on a reference-allele window pools to zeros. Dividing by
    its norm would be a NaN; it must stay a zero row."""
    X = np.array([[0.0, 0.0], [3.0, 4.0]], dtype=np.float32)
    out = prepare(X, "l2")
    assert np.array_equal(out[0], [0.0, 0.0])
    assert np.allclose(out[1], [0.6, 0.8])


def test_zscore_survives_a_dead_dimension():
    X = np.array([[1.0, 5.0], [2.0, 5.0], [3.0, 5.0]], dtype=np.float32)
    out = prepare(X, "zscore")
    assert np.isfinite(out).all()
    assert (out[:, 1] == 0).all()


def test_an_unknown_normalization_is_refused(run):
    with pytest.raises(ValueError, match="normalize must be"):
        prepare(np.zeros((2, 2), dtype=np.float32), "quantile")


# --- design --------------------------------------------------------------------

def test_design_has_a_row_per_window_and_a_locus_key(run):
    frame = design(run)
    assert len(frame) == len(run.vectors)
    assert frame["locus"].nunique() == 6
    assert frame["sample"].nunique() == 5
    assert frame["row"].tolist() == list(range(len(frame)))


def test_log_length_is_defined_for_a_background_window(background):
    """insert_length is 0 there; log10(0) would be -inf and poison every
    correlation it appears in."""
    assert np.isfinite(design(background)["log_length"]).all()


# --- background alignment ------------------------------------------------------

def test_every_alt_row_finds_its_breakpoint(run, background):
    index = background_index(run, background)
    assert (index >= 0).all()
    # All five samples at a locus map to that locus's single background window.
    assert len(set(index.tolist())) == 6


def test_a_missing_breakpoint_is_marked_not_guessed(run, background, subset):
    trimmed = subset(background, slice(1, None))
    index = background_index(run, trimmed)
    assert (index == -1).sum() == 5  # the five samples at the dropped locus


def test_delta_cancels_the_locus_baseline(run, background):
    """The point of the whole background run: on a segment that is pure flank,
    subtracting the reference should leave almost nothing."""
    flank, mask = delta(run, background, "blocks.26", "left")
    junction, _ = delta(run, background, "blocks.26", "junction_5p")
    assert mask.all()
    assert np.abs(flank).mean() < np.abs(junction).mean() / 5


def test_delta_drops_unpaired_rows_and_says_which(run, background, subset):
    trimmed = subset(background, slice(1, None))
    X, mask = delta(run, trimmed, "blocks.26", "junction_5p")
    assert len(X) == mask.sum() == len(run.vectors) - 5


def test_delta_refuses_a_background_from_another_locus_set(run, background, rebuild):
    other = rebuild(
        background, meta={**background.meta, "pos": background.meta["pos"] + 1_000_000}
    )
    with pytest.raises(ValueError, match="no window in the background"):
        delta(run, other, "blocks.26", "junction_5p")


# --- load_runs -----------------------------------------------------------------

def test_shards_concatenate_in_order(tmp_path, run, save_run, subset):
    a, b = tmp_path / "a.npz", tmp_path / "b.npz"
    save_run(a, subset(run, slice(None, 10)))
    save_run(b, subset(run, slice(10, None)))
    merged = load_runs([str(a), str(b)])
    assert len(merged.vectors) == len(run.vectors)
    assert list(merged.meta["svid"]) == list(run.meta["svid"])


def test_shards_built_differently_are_refused(tmp_path, run, save_run, rebuild):
    a, b = tmp_path / "a.npz", tmp_path / "b.npz"
    save_run(a, run)
    save_run(b, rebuild(run, attrs={**run.attrs, "flank": "4096"}))
    with pytest.raises(ValueError, match="flank"):
        load_runs([str(a), str(b)])


def test_no_files_is_an_error_not_an_empty_run():
    with pytest.raises(ValueError, match="no embedding files"):
        load_runs([])
