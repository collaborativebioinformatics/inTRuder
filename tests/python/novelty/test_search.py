"""The Optuna search: axes, objectives and the study."""

from __future__ import annotations

import pandas as pd
import pytest

from novelty.cli import _optional
from novelty.search import (
    Axis,
    agreement,
    balanced_accuracy,
    parse_axis,
    read_truth,
    run_study,
)


def _axis(name, kind, raw):
    return parse_axis(name, kind, raw, optional=_optional)


# --------------------------------------------------------------------------- #
# search space
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw,expected", [
    ("10", (10,)),
    ("0,1,10", (0, 1, 10)),
    ("none", (None,)),
    ("none,5", (None, 5)),
])
def test_categorical_axis(raw, expected):
    axis = _axis("window", int, raw)
    assert axis.values == expected
    assert not axis.is_range


def test_range_axis():
    axis = _axis("window", int, "0:50:5")
    assert axis.is_range
    assert (axis.low, axis.high, axis.step) == (0, 50, 5)
    assert axis.grid_values() == [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50]


def test_a_range_without_a_step_cannot_be_enumerated():
    with pytest.raises(ValueError, match="a grid cannot enumerate"):
        _axis("window", int, "0:50").grid_values()


def test_a_backwards_range_is_rejected():
    with pytest.raises(ValueError, match="50.0 > 10.0"):
        _axis("window", int, "50:10")


def test_a_malformed_range_is_rejected():
    with pytest.raises(ValueError, match="lo:hi"):
        _axis("window", int, "0:1:2:3")


def test_a_single_valued_axis_is_not_searched():
    """Optuna must not be handed a one-choice dimension for every default."""
    assert _axis("window", int, "10").is_fixed
    assert not _axis("window", int, "0,10").is_fixed


# --------------------------------------------------------------------------- #
# objectives
# --------------------------------------------------------------------------- #

def _loci(**columns):
    return pd.DataFrame(columns, index=pd.Index(list(range(len(next(iter(
        columns.values()))))), name="locus"))


def test_agreement_is_one_when_the_platforms_flag_the_same_loci():
    loci = _loci(ucsc=["known", "novel_motif", "novel_locus"],
                 trexplorer=["known", "novel_locus", "novel_motif"])
    assert agreement(loci, ["ucsc", "trexplorer"]) == 1.0


def test_agreement_falls_when_they_disagree():
    loci = _loci(ucsc=["novel_motif", "novel_motif", "known"],
                 trexplorer=["novel_motif", "known", "known"])
    assert agreement(loci, ["ucsc", "trexplorer"]) == pytest.approx(0.5)


def test_agreement_is_zero_when_nothing_is_flagged():
    """Calling everything known must not look like perfect agreement."""
    loci = _loci(ucsc=["known", "known"], trexplorer=["known", "known"])
    assert agreement(loci, ["ucsc", "trexplorer"]) == 0.0


def test_agreement_needs_two_platforms():
    with pytest.raises(ValueError, match="at least two"):
        agreement(_loci(ucsc=["known"]), ["ucsc"])


def test_balanced_accuracy_scores_novel_against_known():
    loci = _loci(novelty=["novel_motif", "known", "novel_locus", "known"])
    truth = pd.Series([True, False, False, False], index=loci.index,
                      name="truth_novel")
    # novel recall 1/1, known recall 2/3
    assert balanced_accuracy(loci, truth) == pytest.approx((1.0 + 2 / 3) / 2)


def test_balanced_accuracy_is_one_on_a_perfect_call():
    loci = _loci(novelty=["novel_motif", "known"])
    truth = pd.Series([True, False], index=loci.index, name="truth_novel")
    assert balanced_accuracy(loci, truth) == 1.0


def test_balanced_accuracy_says_so_when_nothing_matches():
    loci = _loci(novelty=["known"])
    truth = pd.Series([True], index=pd.Index([99], name="locus"), name="truth_novel")
    with pytest.raises(ValueError, match="no locus in the truth table matches"):
        balanced_accuracy(loci, truth)


# --------------------------------------------------------------------------- #
# truth tables
# --------------------------------------------------------------------------- #

def test_read_truth_binarises_the_label(tmp_path):
    path = tmp_path / "truth.tsv"
    path.write_text("chrom\tins_coord\tnovelty\n"
                    "chr1\t100\tnovel_locus\n"
                    "chr1\t200\tknown\n"
                    "chr1\t300\tNOVEL\n")
    truth = read_truth(str(path), ["chrom", "ins_coord"], None)
    assert list(truth) == [True, False, True]
    assert truth.index.names == ["chrom", "ins_coord"]


def test_read_truth_needs_the_locus_columns(tmp_path):
    path = tmp_path / "truth.tsv"
    path.write_text("contig\tpos\tnovelty\nchr1\t100\tknown\n")
    with pytest.raises(ValueError, match="missing locus column"):
        read_truth(str(path), ["chrom", "ins_coord"], None)


def test_read_truth_needs_a_label_column(tmp_path):
    path = tmp_path / "truth.tsv"
    path.write_text("chrom\tins_coord\tnote\nchr1\t100\tx\n")
    with pytest.raises(ValueError, match="--truth-col"):
        read_truth(str(path), ["chrom", "ins_coord"], None)


# --------------------------------------------------------------------------- #
# the study
# --------------------------------------------------------------------------- #

def test_grid_visits_every_point_once():
    axes = [Axis("window", int, values=(0, 10)),
            Axis("max_motif_edits", int, values=(0, 1, 2))]
    seen = []

    def evaluate(params):
        seen.append((params["window"], params["max_motif_edits"]))
        return dict(params), 0.0

    rows = run_study(axes, evaluate, sampler="grid")
    assert len(rows) == 6
    assert sorted(seen) == [(0, 0), (0, 1), (0, 2), (10, 0), (10, 1), (10, 2)]


def test_tpe_optimises_towards_the_better_score():
    """A trivial objective the sampler should learn: bigger window scores higher."""
    axes = [Axis("window", int, low=0, high=50)]

    def evaluate(params):
        return dict(params), float(params["window"])

    rows = run_study(axes, evaluate, sampler="tpe", trials=25, seed=0)
    assert len(rows) == 25
    windows = [row["window"] for row in rows]
    assert max(windows[-10:]) > min(windows[:10])


def test_a_seeded_random_search_is_reproducible():
    axes = [Axis("window", int, low=0, high=50)]

    def run():
        return [row["window"] for row in
                run_study(axes, lambda p: (dict(p), 0.0), sampler="random",
                          trials=8, seed=7)]

    assert run() == run()


def test_trial_metrics_reach_optuna_storage(tmp_path):
    """The whole point of the storage is that the trials outlive the process."""
    import optuna

    url = f"sqlite:///{tmp_path / 'study.db'}"
    axes = [Axis("window", int, values=(0, 10))]
    run_study(axes, lambda p: ({**p, "loci_known": 3}, 0.5), sampler="grid",
              storage=url, study_name="s")

    study = optuna.load_study(study_name="s", storage=url)
    assert len(study.trials) == 2
    assert all(t.user_attrs["loci_known"] == 3 for t in study.trials)
