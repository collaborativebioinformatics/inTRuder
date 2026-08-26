"""End-to-end behaviour of `python -m novelty`."""

from __future__ import annotations

import pandas as pd
import pytest

from novelty.cli import main

_COLUMNS = ("chrom\tins_coord\tSVID\tinsert_size\tsample\trep_start\trep_end\t"
            "motif\tpurity\tmotif_length\trep_length\trep_units\n")
_TRF_TABLE = (
    _COLUMNS
    # inside the TAACCC repeat, pure, and the insertion is nearly all repeat
    + "chr1\t10101\tINS1\t[100]\tS1\t0\t90\tTAACCC\t0.95\t6\t90\t15\n"
    # same locus, a motif the reference does not carry there
    + "chr1\t10101\tINS2\t[100]\tS2\t0\t90\tCAG\t0.95\t3\t90\t30\n"
    # nothing annotated anywhere near
    + "chr1\t500001\tINS3\t[100]\tS3\t0\t90\tCAG\t0.95\t3\t90\t30\n"
    # a pure repeat, but only 10% of the insertion
    + "chr2\t601\tINS4\t[100]\tS4\t0\t10\tAAT\t0.99\t3\t10\t3.3\n"
    # most of the insertion, but a sloppy repeat
    + "chr2\t601\tINS5\t[100]\tS5\t0\t90\tAAT\t0.55\t3\t90\t30\n"
)


@pytest.fixture
def trf_table(tmp_path):
    path = tmp_path / "insertions.trf.tsv"
    path.write_text(_TRF_TABLE)
    return path


def _run(args, capsys):
    code = main(args)
    return code, capsys.readouterr()


def test_platforms_lists_what_can_be_screened_against(capsys):
    code, out = _run(["platforms"], capsys)
    assert code == 0
    assert "ucsc" in out.out and "trexplorer" in out.out
    assert "simplerepeat" in out.out


def test_query_reports_one_locus(write_simplerepeat, capsys):
    code, out = _run(["--platform", "ucsc", "--repeats", str(write_simplerepeat()),
                      "--no-cache", "query", "--chrom", "chr1", "--pos", "10101",
                      "--motif", "TAACCC"], capsys)
    assert code == 0
    assert "status      : known" in out.out
    assert "canonical=AACCCT" in out.out


def test_query_screens_every_platform_and_combines_them(write_simplerepeat,
                                                        write_bed, capsys):
    """The reference knows TAACCC here; a catalogue that does not still says novel."""
    code, out = _run([
        "--platform", "ucsc,bed",
        "--repeats", f"ucsc={write_simplerepeat()}",
        "--repeats", f"bed={write_bed(rows=[('chr1', 10000, 10468, 'CAG')])}",
        "--no-cache", "query", "--chrom", "chr1", "--pos", "10101", "--motif", "TAACCC",
    ], capsys)
    assert code == 0
    assert "combined      : known" in out.out


def test_a_bare_repeats_path_needs_a_single_platform(write_simplerepeat, capsys):
    with pytest.raises(SystemExit, match="ambiguous"):
        main(["--platform", "ucsc,bed", "--repeats", str(write_simplerepeat()),
              "query", "--chrom", "chr1", "--pos", "1", "--motif", "AT"])


# --------------------------------------------------------------------------- #
# annotate
# --------------------------------------------------------------------------- #

def _annotate(trf_table, tmp_path, write_simplerepeat, capsys, *extra, options=()):
    """Run `annotate`; `options` are global flags, which precede the subcommand."""
    out = tmp_path / "annotated.tsv"
    code, captured = _run([
        "--platform", "ucsc", "--repeats", str(write_simplerepeat()), "--no-cache",
        *options,
        "annotate", str(trf_table), str(out), "--insertion-key", "chrom,ins_coord,SVID",
        *extra,
    ], capsys)
    assert code == 0, captured.err
    return pd.read_csv(out, sep="\t"), captured


def test_annotate_classifies_every_row(trf_table, tmp_path, write_simplerepeat, capsys):
    frame, _ = _annotate(trf_table, tmp_path, write_simplerepeat, capsys)
    assert list(frame.novelty) == ["known", "novel_motif", "novel_locus",
                                   "known", "known"]
    assert list(frame.ucsc_novelty) == list(frame.novelty)


def test_annotate_keeps_the_input_columns_and_row_order(trf_table, tmp_path,
                                                        write_simplerepeat, capsys):
    frame, _ = _annotate(trf_table, tmp_path, write_simplerepeat, capsys)
    original = pd.read_csv(trf_table, sep="\t")
    assert list(frame.columns[:len(original.columns)]) == list(original.columns)
    assert list(frame.SVID) == list(original.SVID)


def test_annotate_reports_reference_coordinates_in_the_input_convention(
        trf_table, tmp_path, write_simplerepeat, capsys):
    """simpleRepeat [10000, 10468) is 1-based 10001..10468, and POS is 1-based."""
    frame, _ = _annotate(trf_table, tmp_path, write_simplerepeat, capsys)
    assert (frame.ucsc_start[0], frame.ucsc_end[0]) == (10001, 10468)

    zero_based = _annotate(trf_table, tmp_path, write_simplerepeat, capsys,
                           options=("--coord-base", "0"))[0]
    assert (zero_based.ucsc_start[0], zero_based.ucsc_end[0]) == (10000, 10468)


def test_annotate_computes_insertion_purity(trf_table, tmp_path,
                                            write_simplerepeat, capsys):
    frame, _ = _annotate(trf_table, tmp_path, write_simplerepeat, capsys)
    assert list(frame.insertion_repeat_bases) == [90, 90, 90, 10, 90]
    assert list(frame.insertion_purity) == [0.9, 0.9, 0.9, 0.1, 0.9]


def test_annotate_flags_but_keeps_filtered_rows(trf_table, tmp_path,
                                                write_simplerepeat, capsys):
    frame, captured = _annotate(trf_table, tmp_path, write_simplerepeat, capsys,
                                "--min-purity", "0.8", "--min-insertion-purity", "0.8")
    assert list(frame["filter"]) == ["PASS", "PASS", "PASS",
                                     "low_insertion_purity", "low_purity"]
    assert len(frame) == 5
    assert "2 row(s) failed a filter" in captured.err


def test_drop_filtered_writes_only_passing_rows(trf_table, tmp_path,
                                                write_simplerepeat, capsys):
    frame, _ = _annotate(trf_table, tmp_path, write_simplerepeat, capsys,
                         "--min-purity", "0.8", "--min-insertion-purity", "0.8",
                         "--drop-filtered")
    assert list(frame.SVID) == ["INS1", "INS2", "INS3"]


def test_summary_counts_loci_as_well_as_rows(trf_table, tmp_path,
                                             write_simplerepeat, capsys):
    """Rows are locus x sample x call, so per-row percentages track recurrence."""
    _, captured = _annotate(trf_table, tmp_path, write_simplerepeat, capsys)
    assert "per row (n=5)" in captured.err
    assert "per locus (chrom+ins_coord) (n=3)" in captured.err


def test_annotate_across_two_platforms(trf_table, tmp_path, write_simplerepeat,
                                       write_bed, capsys):
    """A locus is only novel when no catalogue has it."""
    out = tmp_path / "both.tsv"
    code, captured = _run([
        "--platform", "ucsc,bed",
        "--repeats", f"ucsc={write_simplerepeat()}",
        "--repeats", f"bed={write_bed(rows=[('chr1', 500000, 500100, 'CAG')])}",
        "--no-cache", "annotate", str(trf_table), str(out),
        "--insertion-key", "chrom,ins_coord,SVID",
    ], capsys)
    assert code == 0, captured.err

    frame = pd.read_csv(out, sep="\t")
    # chr1:500001 is novel_locus to UCSC but known to the BED catalogue.
    assert frame.ucsc_novelty[2] == "novel_locus"
    assert frame.bed_novelty[2] == "known"
    assert frame.novelty[2] == "known"
    # The BED catalogue carries no TRF annotations, so it contributes no columns.
    assert "ucsc_per_match" in frame.columns
    assert "bed_per_match" not in frame.columns


def test_annotate_says_which_column_is_missing(trf_table, tmp_path,
                                               write_simplerepeat, capsys):
    code, captured = _run([
        "--platform", "ucsc", "--repeats", str(write_simplerepeat()), "--no-cache",
        "annotate", str(trf_table), str(tmp_path / "x.tsv"), "--motif-col", "unit",
    ], capsys)
    assert code == 2
    assert "'unit' not in" in captured.err


def test_unknown_platform_is_rejected_by_the_parser(capsys):
    with pytest.raises(SystemExit):
        main(["--platform", "ensembl", "query", "--chrom", "chr1", "--pos", "1",
              "--motif", "AT"])


def test_a_missing_catalogue_is_an_error_not_a_traceback(tmp_path, capsys):
    code, captured = _run(["--platform", "ucsc", "--repeats",
                           str(tmp_path / "absent.txt.gz"), "--no-download",
                           "query", "--chrom", "chr1", "--pos", "1", "--motif", "AT"],
                          capsys)
    assert code == 1
    assert "not found" in captured.err


def test_a_bad_filter_column_fails_before_loading_a_catalogue(trf_table, tmp_path,
                                                              capsys):
    """The catalogues cost 20s to load; argument mistakes should not wait for them."""
    code, captured = _run([
        "--platform", "ucsc", "--repeats", str(tmp_path / "never-read.txt.gz"),
        "--no-download", "annotate", str(trf_table), str(tmp_path / "x.tsv"),
        "--min-purity", "0.8", "--purity-col", "identity",
    ], capsys)
    assert code == 2
    assert "cannot filter on 'identity'" in captured.err


def test_min_insertion_purity_needs_the_purity_columns(trf_table, tmp_path, capsys):
    code, captured = _run([
        "--platform", "ucsc", "--repeats", str(tmp_path / "never-read.txt.gz"),
        "--no-download", "annotate", str(trf_table), str(tmp_path / "x.tsv"),
        "--no-insertion-purity", "--min-insertion-purity", "0.8",
    ], capsys)
    assert code == 2
    assert "--no-insertion-purity" in captured.err


# --------------------------------------------------------------------------- #
# hyperparameters
# --------------------------------------------------------------------------- #

def test_every_hyperparameter_is_exposed_on_annotate_and_sweep():
    """The declaration table is the single source; both commands must wire it up."""
    from novelty.cli import HYPERPARAMS, build_parser
    parser = build_parser()
    actions = {a.dest for sub in parser._subparsers._group_actions
               for name, sp in sub.choices.items() if name in ("annotate", "sweep")
               for a in sp._actions}
    assert {h.name for h in HYPERPARAMS} <= actions


@pytest.mark.parametrize("flag,value,expected", [
    ("--min-motif-length", "4", ["PASS", "short_motif", "short_motif",
                                 "short_motif", "short_motif"]),
    ("--max-motif-length", "3", ["long_motif", "PASS", "PASS", "PASS", "PASS"]),
    ("--min-rep-length", "50", ["PASS", "PASS", "PASS", "short_repeat", "PASS"]),
    ("--min-rep-units", "5", ["PASS", "PASS", "PASS", "few_units", "PASS"]),
])
def test_row_filter_hyperparameters(trf_table, tmp_path, write_simplerepeat, capsys,
                                    flag, value, expected):
    frame, _ = _annotate(trf_table, tmp_path, write_simplerepeat, capsys, flag, value)
    assert list(frame["filter"]) == expected


def test_none_turns_a_threshold_off(trf_table, tmp_path, write_simplerepeat, capsys):
    """A sweep axis needs to be able to say "no filter" alongside real values."""
    frame, _ = _annotate(trf_table, tmp_path, write_simplerepeat, capsys,
                         "--min-purity", "none")
    assert set(frame["filter"]) == {"PASS"}


def test_max_fuzzy_motif_is_accepted_and_passed_through(trf_table, tmp_path,
                                                        write_simplerepeat, capsys):
    """Its effect is exercised in test_catalog; here it just has to reach the screen."""
    frame, _ = _annotate(trf_table, tmp_path, write_simplerepeat, capsys,
                         "--max-motif-edits", "1", "--max-fuzzy-motif", "2")
    assert list(frame.novelty) == ["known", "novel_motif", "novel_locus",
                                   "known", "known"]


def test_reference_identity_threshold_discounts_a_sloppy_reference_repeat(
        trf_table, tmp_path, write_simplerepeat, capsys):
    """perMatch 95 for the TAACCC row: at 96 it stops counting as annotation."""
    kept = _annotate(trf_table, tmp_path, write_simplerepeat, capsys,
                     "--min-reference-identity", "90")[0]
    dropped = _annotate(trf_table, tmp_path, write_simplerepeat, capsys,
                        "--min-reference-identity", "96")[0]
    assert kept.novelty[0] == "known"
    assert dropped.ucsc_n_nearby[0] == 0
    assert dropped.novelty[0] == "novel_locus"


def test_reference_length_threshold_discounts_a_short_reference_repeat(
        trf_table, tmp_path, write_simplerepeat, capsys):
    frame, _ = _annotate(trf_table, tmp_path, write_simplerepeat, capsys,
                         "--min-reference-length", "1000")
    assert set(frame.ucsc_n_nearby) == {0}
    assert set(frame.novelty) == {"novel_locus"}


def test_a_reference_threshold_a_catalogue_cannot_apply_is_announced(
        trf_table, tmp_path, write_simplerepeat, write_bed, capsys):
    """BED has no perMatch column, so the threshold cannot bite -- say so."""
    out = tmp_path / "both.tsv"
    code, captured = _run([
        "--platform", "ucsc,bed",
        "--repeats", f"ucsc={write_simplerepeat()}",
        "--repeats", f"bed={write_bed()}",
        "--no-cache", "annotate", str(trf_table), str(out),
        "--insertion-key", "chrom,ins_coord,SVID", "--min-reference-identity", "96",
    ], capsys)
    assert code == 0, captured.err
    assert "bed: no column for min_identity" in captured.err
    frame = pd.read_csv(out, sep="\t")
    assert frame.ucsc_n_nearby[0] == 0        # filtered out of UCSC
    assert frame.bed_n_nearby[0] == 1         # untouched in the BED catalogue


# --------------------------------------------------------------------------- #
# sweep
# --------------------------------------------------------------------------- #

def _sweep(trf_table, tmp_path, write_simplerepeat, capsys, *extra, out=None):
    out = out or tmp_path / "sweep.tsv"
    code, captured = _run([
        "--platform", "ucsc", "--repeats", str(write_simplerepeat()), "--no-cache",
        "sweep", str(trf_table), str(out), "--insertion-key", "chrom,ins_coord,SVID",
        *extra,
    ], capsys)
    assert code == 0, captured.err
    return pd.read_csv(out, sep="\t"), captured


def test_grid_sampling_runs_the_cartesian_product(trf_table, tmp_path,
                                                  write_simplerepeat, capsys):
    frame, captured = _sweep(trf_table, tmp_path, write_simplerepeat, capsys,
                             "--window", "0,10", "--max-motif-edits", "0,1",
                             "--min-purity", "none,0.8")
    assert len(frame) == 2 * 2 * 2
    assert set(zip(frame.window, frame.max_motif_edits)) == {(0, 0), (0, 1),
                                                             (10, 0), (10, 1)}
    assert "grid sampler, 8 trial(s)" in captured.err


def test_a_range_axis_is_enumerated_by_the_grid(trf_table, tmp_path,
                                                write_simplerepeat, capsys):
    frame, _ = _sweep(trf_table, tmp_path, write_simplerepeat, capsys,
                      "--window", "0:10:5")
    assert sorted(frame.window) == [0, 5, 10]


def test_a_range_without_a_step_cannot_be_gridded(trf_table, tmp_path,
                                                  write_simplerepeat, capsys):
    code, captured = _run([
        "--platform", "ucsc", "--repeats", str(write_simplerepeat()), "--no-cache",
        "sweep", str(trf_table), str(tmp_path / "s.tsv"),
        "--insertion-key", "chrom,ins_coord,SVID", "--window", "0:10",
    ], capsys)
    assert code == 2
    assert "a grid cannot enumerate" in captured.err


def test_trials_differing_only_in_row_filters_reuse_the_screen(
        trf_table, tmp_path, write_simplerepeat, capsys, monkeypatch):
    """Row filters do not change the screen, so they must not trigger a re-screen."""
    from novelty import cli

    calls = []
    original = cli._screen
    monkeypatch.setattr(cli, "_screen", lambda *a, **k: (calls.append(1),
                                                         original(*a, **k))[1])
    frame, _ = _sweep(trf_table, tmp_path, write_simplerepeat, capsys,
                      "--window", "0,10", "--min-purity", "none,0.5,0.8")
    assert len(frame) == 6
    assert len(calls) == 2


def test_sweep_records_every_hyperparameter_and_the_counts(trf_table, tmp_path,
                                                           write_simplerepeat, capsys):
    from novelty.cli import HYPERPARAMS
    frame, _ = _sweep(trf_table, tmp_path, write_simplerepeat, capsys)
    assert {h.name for h in HYPERPARAMS} <= set(frame.columns)
    for column in ("n_rows", "n_rows_pass", "n_loci", "loci_known", "frac_loci_novel",
                   "ucsc_loci_known"):
        assert column in frame.columns
    assert len(frame) == 1                       # all defaults == one combination


def test_sweep_and_annotate_metrics_agree(trf_table, tmp_path, write_simplerepeat,
                                          capsys):
    """`annotate --metrics` writes a row in the same layout the sweep does."""
    swept, _ = _sweep(trf_table, tmp_path, write_simplerepeat, capsys,
                      "--max-motif-edits", "1")
    metrics = tmp_path / "one.tsv"
    _annotate(trf_table, tmp_path, write_simplerepeat, capsys,
              "--max-motif-edits", "1", "--metrics", str(metrics))
    single = pd.read_csv(metrics, sep="\t")
    # the sweep adds the two search-only columns; everything else must line up
    assert list(swept.columns) == [*single.columns, "objective", "score"]
    pd.testing.assert_frame_equal(single, swept[single.columns])


def test_metrics_appends_so_an_external_loop_can_accumulate(trf_table, tmp_path,
                                                            write_simplerepeat, capsys):
    metrics = tmp_path / "runs.tsv"
    for edits in ("0", "1"):
        _annotate(trf_table, tmp_path, write_simplerepeat, capsys,
                  "--max-motif-edits", edits, "--metrics", str(metrics))
    frame = pd.read_csv(metrics, sep="\t")
    assert list(frame.max_motif_edits) == [0, 1]
