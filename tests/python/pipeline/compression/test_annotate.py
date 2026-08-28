"""The file-in/file-out contract for the compressibility annotator.

The claim the step rests on is that a repetitive insertion compresses far better
than a random one, so the ratio separates the two by a wide margin. That is what
these tests pin down, along with the VCF it hands back.
"""

from __future__ import annotations

import random
import sys

import pysam
import pytest

from intruder.pipeline.compression.annotate import main

# A perfect (AT)n tandem repeat, and a same-length sequence with no structure at
# all. Seeded so the ratios below are the same on every machine.
REPETITIVE = "AT" * 500
RANDOM = "".join(random.Random(0).choices("ACGT", k=1000))

HEADER = """##fileformat=VCFv4.2
##contig=<ID=chr1,length=248956422>
##INFO=<ID=SVTYPE,Number=1,Type=String,Description="Type of SV">
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO
"""

ROWS = [
    ("100", "INS.repetitive", "A", "A" + REPETITIVE),
    ("200", "INS.random", "C", "C" + RANDOM),
    # two ALTs on one record: the field has to carry one ratio per allele
    ("300", "INS.multi", "G", f"G{REPETITIVE},G{RANDOM}"),
]


@pytest.fixture
def annotated(tmp_path, monkeypatch):
    """Run the CLI over a synthetic VCF and hand back the records it wrote."""
    src = tmp_path / "in.vcf"
    src.write_text(
        HEADER + "".join(
            f"chr1\t{pos}\t{name}\t{ref}\t{alt}\t60\tPASS\tSVTYPE=INS\n"
            for pos, name, ref, alt in ROWS
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.vcf"
    monkeypatch.setattr(sys, "argv", ["compression", "-i", str(src), "-o", str(out)])
    main()
    with pysam.VariantFile(out) as vcf:
        return vcf.header, list(vcf)


def ratios(record) -> list[float]:
    """SVCOMP as numbers, however pysam chose to split the comma-joined field."""
    value = record.info["SVCOMP"]
    if isinstance(value, str):
        value = value.split(",")
    return [float(part) for chunk in value for part in str(chunk).split(",")]


def test_svcomp_is_declared_in_the_output_header(annotated):
    header, _ = annotated
    assert "SVCOMP" in header.info


def test_every_record_survives_with_its_original_fields(annotated):
    _, records = annotated
    assert [r.id for r in records] == [name for _, name, _, _ in ROWS]
    assert [r.pos for r in records] == [100, 200, 300]
    assert {r.info["SVTYPE"] for r in records} == {"INS"}


def test_a_repetitive_allele_compresses_far_better_than_a_random_one(annotated):
    _, records = annotated
    repetitive = ratios(records[0])[0]
    noise = ratios(records[1])[0]
    # (AT)n collapses to a handful of bytes; random ACGT bottoms out around the
    # two bits per base Huffman can manage. An order of magnitude apart.
    assert repetitive > 10 * noise
    assert repetitive > 20
    assert noise < 5


def test_the_ratio_is_raw_bytes_over_compressed_bytes(annotated):
    import zlib

    _, records = annotated
    alt = "A" + REPETITIVE
    expected = len(alt.encode()) / len(zlib.compress(alt.encode()))
    assert ratios(records[0])[0] == pytest.approx(expected)


def test_one_ratio_is_written_per_alt_allele(annotated):
    _, records = annotated
    assert len(ratios(records[0])) == 1
    assert len(ratios(records[2])) == 2
    # and the pair matches the single-ALT records for the same two sequences
    multi = ratios(records[2])
    assert multi[0] == pytest.approx(ratios(records[0])[0])
    assert multi[1] == pytest.approx(ratios(records[1])[0])
