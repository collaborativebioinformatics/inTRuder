"""Shared fixtures: small catalogue files in each supported layout."""

from __future__ import annotations

import gzip

import pytest

from novelty import RepeatCatalog

# chr1:10001-10468 in 1-based terms, motif TAACCC (the telomeric repeat).
SIMPLEREPEAT_ROWS = [
    (585, "chr1", 10000, 10468, "trf", 6, 77.2, 6, 95, 3, 789, 33, 51, 0, 15, 1.43,
     "TAACCC"),
    (585, "chr1", 20000, 20100, "trf", 2, 50.0, 2, 100, 0, 200, 0, 50, 50, 0, 1.00,
     "GC"),
    (585, "chr2", 500, 800, "trf", 3, 100.0, 3, 98, 1, 400, 66, 0, 0, 33, 0.92,
     "AAT"),
]

SIMPLEREPEAT_HEADER = (
    "#bin\tchrom\tchromStart\tchromEnd\tname\tperiod\tcopyNum\tconsensusSize\t"
    "perMatch\tperIndel\tscore\tA\tC\tG\tT\tentropy\tsequence\n"
)


@pytest.fixture
def write_simplerepeat(tmp_path):
    """Write a UCSC simpleRepeat table; raw dump by default, hgTables on request."""

    def _write(rows=SIMPLEREPEAT_ROWS, *, header=False, gzipped=True, name=None):
        path = tmp_path / (name or ("simpleRepeat.txt.gz" if gzipped
                                    else "simpleRepeat.txt"))
        opener = gzip.open if gzipped else open
        with opener(path, "wt") as handle:
            if header:
                handle.write(SIMPLEREPEAT_HEADER)
            for row in rows:
                handle.write("\t".join(str(v) for v in row) + "\n")
        return path

    return _write


@pytest.fixture
def write_bed(tmp_path):
    """Write a TRExplorer-style BED4 catalogue (chrom start end motif score)."""

    def _write(rows=(("chr1", 10000, 10468, "TAACCC"),
                     ("chr1", 20000, 20100, "GC"),
                     ("chr2", 500, 800, "AAT")), name="catalog.bed"):
        path = tmp_path / name
        path.write_text("".join(
            f"{c}\t{s}\t{e}\t{m}\t.\n" for c, s, e, m in rows))
        return path

    return _write


@pytest.fixture
def catalog(write_simplerepeat):
    return RepeatCatalog.from_file(write_simplerepeat(), platform="ucsc",
                                   verbose=False, cache=False)
