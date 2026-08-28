"""Tests for the catalogue join behind `uv run join-hits`.

polars is in the `analysis` uv group, not the runtime set, so these skip on a
plain `uv sync` -- which is what CI runs. To exercise them:
`uv sync --group analysis && uv run pytest tests/python/analysis`.
"""

from __future__ import annotations

import csv
import gzip

import pytest

pytest.importorskip("polars")

from intruder.analysis.benchmark.join_hits import main

QUERY_HEADER = ["chrom", "ins_coord", "SVID", "motif"]
QUERY_ROWS = [
    ["chr1", "100", "INS1", "AT"],
    ["chr1", "200", "INS2", "GC"],
    ["chr1", "300", "INS3", "TTA"],
]


def hit_row(chrom: str, ins_coord: str, svid: str, motif: str) -> list[str]:
    """One line of `bedtools intersect` output, in HITS_COLUMNS order."""
    return [
        chrom, ins_coord, str(int(ins_coord) + 1), svid,
        "0", "50", "HG1", "0", "20", motif, "0.9", str(len(motif)), "20", "10",
    ]


def write_tsv(path, rows, header=None):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        if header:
            writer.writerow(header)
        writer.writerows(rows)
    return path


def run_join(monkeypatch, tmp_path, hits_rows, query_rows=QUERY_ROWS, header=QUERY_HEADER):
    """Drive the CLI over a query and a hits file; return the labelled rows."""
    query = write_tsv(tmp_path / "query.tsv", query_rows, header)
    hits = write_tsv(tmp_path / "hits.bed", hits_rows)
    output = tmp_path / "labelled.tsv"
    monkeypatch.setattr(
        "sys.argv",
        ["join-hits", "--query", str(query), "--hits", str(hits), "--output", str(output)],
    )
    main()
    # The module appends the suffix itself: `--output x` writes `x.gz`.
    with gzip.open(f"{output}.gz", "rt", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def verdicts(rows):
    return {row["SVID"]: row["in_catalog"] for row in rows}


# The first line of the hits file is consumed as a header (see the xfail at the
# bottom), and polars needs at least one surviving data row to infer the key
# types, so every fixture below opens with two rows nothing in the query matches.
FILLER = [hit_row("chr9", "999", "IGNORED", "AAAA"), hit_row("chr9", "1000", "IGNORED", "AAAA")]


def test_labels_hits_true_and_misses_false(monkeypatch, tmp_path):
    hits = [*FILLER, hit_row("chr1", "100", "INS1", "AT"), hit_row("chr1", "300", "INS3", "TTA")]
    assert verdicts(run_join(monkeypatch, tmp_path, hits)) == {
        "INS1": "true",
        "INS2": "false",
        "INS3": "true",
    }


def test_a_hit_must_match_on_every_shared_column(monkeypatch, tmp_path):
    # Right locus and SVID, wrong motif: not the same repeat, so not a hit.
    hits = [*FILLER, hit_row("chr1", "200", "INS2", "CAG")]
    assert verdicts(run_join(monkeypatch, tmp_path, hits))["INS2"] == "false"


def test_every_query_row_survives_the_join(monkeypatch, tmp_path):
    """Left join: no query row is dropped, and a doubled hit adds no duplicate."""
    hits = [*FILLER] + [hit_row("chr1", "200", "INS2", "GC")] * 2
    rows = run_join(monkeypatch, tmp_path, hits)
    assert sorted(row["SVID"] for row in rows) == ["INS1", "INS2", "INS3"]


def test_query_columns_are_preserved(monkeypatch, tmp_path):
    rows = run_join(monkeypatch, tmp_path, FILLER)
    assert list(rows[0]) == [*QUERY_HEADER, "in_catalog"]


def test_no_shared_columns_is_an_error(monkeypatch, tmp_path):
    with pytest.raises(SystemExit):
        run_join(
            monkeypatch,
            tmp_path,
            FILLER,
            query_rows=[["x"], ["y"]],
            header=["unrelated"],
        )


@pytest.mark.xfail(
    reason="scan_csv(has_header=True) eats the first line of the headerless "
           "bedtools output, so the first intersection is never labelled",
)
def test_first_hit_in_the_file_is_labelled(monkeypatch, tmp_path):
    hits = [hit_row("chr1", "100", "INS1", "AT")]
    assert verdicts(run_join(monkeypatch, tmp_path, hits))["INS1"] == "true"
