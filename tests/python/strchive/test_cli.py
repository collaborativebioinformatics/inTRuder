"""The file-in/file-out contract: what ``annotate`` reads and what it writes."""

from __future__ import annotations

import csv

import pytest

from strchive.__main__ import _number, main
from strchive.compare import OUTPUT_COLUMNS

HEADER = ["chrom", "ins_coord", "SVID", "sample", "motif", "rep_units", "gene"]
ROWS = [
    # a pathogenic CCG expansion at ABCD3
    ["chr1", "94418430", "INS.1", "HG00001", "CCG", "120", "ABCD3"],
    # the same locus, benign copy number
    ["chr1", "94418430", "INS.2", "HG00002", "CCG", "10", "ABCD3"],
    # a motif nobody has catalogued at that locus
    ["chr1", "94418430", "INS.3", "HG00003", "AATTG", "40", "ABCD3"],
    # RFC1 carrying the reference motif rather than a pathogenic one
    ["chr4", "39348430", "INS.4", "HG00004", "AAAAG", "500", "RFC1"],
    # nowhere near a disease locus
    ["chr1", "66378", "INS.5", "HG00005", "TATAT", "31", ""],
]


@pytest.fixture
def table(tmp_path):
    path = tmp_path / "candidates.tsv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(HEADER)
        writer.writerows(ROWS)
    return path


def run(fixture_path, *args) -> int:
    return main(["annotate", *[str(a) for a in args],
                 "--catalog", str(fixture_path), "--strchive-version", "v2.26.0-test"])


def read(path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


@pytest.mark.parametrize("cell,expected", [
    ("138", 138.0), ("[138]", 138.0), ("[0 0]", 0.0), ("7.7", 7.7),
    ("[-5]", -5.0), ("", None), (None, None), ("n/a", None),
])
def test_number_tolerates_the_callers_bracketed_lists(cell, expected):
    assert _number(cell) == expected


def test_annotate_preserves_input_columns_and_row_order(table, tmp_path, fixture_path):
    out = tmp_path / "out.tsv"
    assert run(fixture_path, table, out) == 0
    rows = read(out)
    assert [r["SVID"] for r in rows] == [r[2] for r in ROWS]
    for original, row in zip(ROWS, rows):
        assert [row[c] for c in HEADER] == original


def test_annotate_appends_every_output_column(table, tmp_path, fixture_path):
    out = tmp_path / "out.tsv"
    run(fixture_path, table, out)
    with open(out, encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
    assert header == HEADER + list(OUTPUT_COLUMNS)


def test_annotate_assigns_the_expected_statuses(table, tmp_path, fixture_path):
    out = tmp_path / "out.tsv"
    run(fixture_path, table, out)
    assert [r["strchive_status"] for r in read(out)] == [
        "pathogenic_expansion",
        "pathogenic_motif",
        "locus_novel_motif",
        "locus_known_motif",
        "no_locus_match",
    ]


def test_annotate_carries_the_catalog_version_into_every_row(table, tmp_path, fixture_path):
    out = tmp_path / "out.tsv"
    run(fixture_path, table, out)
    assert {r["strchive_catalog"] for r in read(out)} == {"STRchive v2.26.0-test (hg38)"}


def test_re_annotating_replaces_rather_than_duplicates(table, tmp_path, fixture_path):
    first, second = tmp_path / "one.tsv", tmp_path / "two.tsv"
    run(fixture_path, table, first)
    run(fixture_path, first, second)
    with open(second, encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
    assert len(header) == len(set(header))
    assert header == HEADER + list(OUTPUT_COLUMNS)
    assert read(first) == read(second)


def test_missing_required_column_fails_loudly(tmp_path, fixture_path):
    path = tmp_path / "bad.tsv"
    path.write_text("chrom\tposition\tunit\nchr1\t100\tAT\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="required column"):
        run(fixture_path, path, tmp_path / "out.tsv")


def test_column_names_are_overridable(tmp_path, fixture_path):
    path = tmp_path / "renamed.tsv"
    path.write_text("contig\tposition\tunit\ncr1\t94418430\tCCG\n".replace("cr1", "chr1"),
                    encoding="utf-8")
    out = tmp_path / "out.tsv"
    assert main(["annotate", str(path), str(out), "--catalog", str(fixture_path),
                 "--strchive-version", "v2.26.0-test", "--col-chrom", "contig",
                 "--col-pos", "position", "--col-motif", "unit"]) == 0
    assert read(out)[0]["strchive_id"] == "OPDM5_ABCD3"


def test_optional_columns_may_be_absent(tmp_path, fixture_path):
    """gene and rep_units are optional: their absence degrades, not fails."""
    path = tmp_path / "minimal.tsv"
    path.write_text("chrom\tins_coord\tmotif\nchr1\t94418430\tCCG\n", encoding="utf-8")
    out = tmp_path / "out.tsv"
    assert run(fixture_path, path, out) == 0
    row = read(out)[0]
    assert row["strchive_status"] == "pathogenic_motif"
    assert row["strchive_est_copies"] == ""
    assert row["strchive_gene_agrees"] == ""


def test_empty_table_writes_a_header_only(tmp_path, fixture_path):
    path = tmp_path / "empty.tsv"
    path.write_text("chrom\tins_coord\tmotif\n", encoding="utf-8")
    out = tmp_path / "out.tsv"
    assert run(fixture_path, path, out) == 0
    assert read(out) == []


def test_query_runs_end_to_end(fixture_path, capsys):
    assert main(["query", "--chrom", "chr1", "--pos", "94418430", "--motif", "CCG",
                 "--rep-units", "120", "--catalog", str(fixture_path),
                 "--strchive-version", "v2.26.0-test"]) == 0
    out = capsys.readouterr().out
    assert "pathogenic_expansion" in out
    assert "OPDM5_ABCD3" in out
