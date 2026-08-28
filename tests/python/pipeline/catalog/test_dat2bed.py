"""Parsing TRF `.dat` output into a BED4 catalogue.

The conversion is one line of arithmetic, and it is the line everything
downstream depends on: TRF reports 1-based inclusive coordinates, BED is 0-based
half-open, and getting it wrong shifts every interval in the catalogue by one
base without failing anything loudly.
"""

from __future__ import annotations

from intruder.pipeline.catalog.dat2bed import convert

# The real header TRF writes, trimmed to the parts the parser reacts to: the
# `Sequence:` line it takes the contig from, and lines it must ignore.
HEADER = """\
Tandem Repeats Finder Program written by:

Sequence: chr1

Parameters: 2 5 5 80 10 50 500


"""

# start end period copies consensusSize %match %indel score A C G T entropy consensus aligned
FIELDS = "6 77.2 6 95 0 610 0 25 25 50 1.52"


def data_line(start, end, motif, fields=FIELDS):
    return f"{start} {end} {fields} {motif} {motif * 3}"


def write_dat(tmp_path, name, body, header=HEADER):
    path = tmp_path / name
    path.write_text(header + body)
    return path


def read_bed(path):
    return [line.split("\t") for line in path.read_text().splitlines()]


def test_start_is_shifted_but_end_is_not(tmp_path):
    """1-based inclusive [start, end] becomes 0-based half-open [start-1, end).

    Both conventions name the same bases, so the interval keeps its length and
    only the start moves.
    """
    dat = write_dat(tmp_path, "chr1.dat", data_line(10001, 10468, "TAACCC") + "\n")
    out = tmp_path / "out.bed"

    assert convert([dat], out) == (1, 0)
    assert read_bed(out) == [["chr1", "10000", "10468", "TAACCC"]]


def test_a_single_base_repeat_keeps_a_width_of_one(tmp_path):
    """The edge case that separates an off-by-one from a correct conversion."""
    dat = write_dat(tmp_path, "chr1.dat", data_line(1, 1, "A") + "\n")
    out = tmp_path / "out.bed"

    convert([dat], out)
    chrom, start, end, _ = read_bed(out)[0]
    assert (start, end) == ("0", "1")
    assert int(end) - int(start) == 1
    assert chrom == "chr1"


def test_contig_comes_from_the_sequence_header(tmp_path):
    """`Sequence: chr7 ...` carries a description after the name; take the name."""
    header = HEADER.replace("Sequence: chr1", "Sequence: chr7 dna:chromosome GRCh38")
    dat = write_dat(tmp_path, "whatever.dat", data_line(500, 560, "CAG") + "\n", header=header)
    out = tmp_path / "out.bed"

    convert([dat], out)
    assert read_bed(out)[0][0] == "chr7"


def test_contig_falls_back_to_the_filename_without_a_header(tmp_path):
    dat = write_dat(tmp_path, "chrX.fa.2.5.5.dat", data_line(90, 120, "GT") + "\n", header="")
    out = tmp_path / "out.bed"

    convert([dat], out)
    assert read_bed(out)[0][0] == "chrX"


def test_a_new_sequence_header_switches_contig_mid_file(tmp_path):
    """One `.dat` can hold several sequences; rows must follow the latest header."""
    body = (
        data_line(100, 130, "AT") + "\n"
        + "Sequence: chr2\n"
        + data_line(200, 230, "GC") + "\n"
    )
    dat = write_dat(tmp_path, "multi.dat", body)
    out = tmp_path / "out.bed"

    convert([dat], out)
    assert [(row[0], row[1]) for row in read_bed(out)] == [("chr1", "99"), ("chr2", "199")]


def test_malformed_lines_are_skipped_and_counted(tmp_path):
    """Truncated and non-numeric records are dropped, but the good ones survive.

    A short write or an interrupted TRF run leaves a partial last line, and one
    bad line must not lose the rest of the chromosome.
    """
    body = "\n".join([
        data_line(10001, 10468, "TAACCC"),
        "10500 10520 6 3.5 6 95",                       # truncated: under 14 fields
        data_line("10600", "not-a-number", "CAG"),      # coordinates that will not parse
        data_line(10700, 10730, "GGC"),
    ]) + "\n"
    dat = write_dat(tmp_path, "chr1.dat", body)
    out = tmp_path / "out.bed"

    assert convert([dat], out) == (2, 2)
    assert [row[3] for row in read_bed(out)] == ["TAACCC", "GGC"]


def test_blank_and_narrative_lines_are_not_counted_as_malformed(tmp_path):
    """Only lines that look like records count; header prose is not an error."""
    dat = write_dat(tmp_path, "chr1.dat", data_line(10001, 10468, "TAACCC") + "\n")
    out = tmp_path / "out.bed"

    assert convert([dat], out)[1] == 0


def test_rows_from_several_files_are_merged_and_sorted(tmp_path):
    """The builder passes `dat/*.dat` in shell glob order; output must be sorted."""
    second = write_dat(tmp_path, "chr2.dat", data_line(50, 60, "TA") + "\n",
                       header=HEADER.replace("chr1", "chr2"))
    first = write_dat(tmp_path, "chr1.dat", "\n".join([
        data_line(900, 950, "CAG"),
        data_line(100, 150, "AT"),
    ]) + "\n")
    out = tmp_path / "out.bed"

    assert convert([second, first], out) == (3, 0)
    assert [(row[0], int(row[1])) for row in read_bed(out)] == [
        ("chr1", 99), ("chr1", 899), ("chr2", 49),
    ]
