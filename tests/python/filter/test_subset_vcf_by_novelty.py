"""Tests for the novelty -> VCF subset step.

Every test here is a trap that produced a plausible WRONG VCF rather than an
error when the join was first written against `SVID`. A subset that is quietly
too big or too small costs GPU hours and is not visible until the embeddings
come back short.
"""

from __future__ import annotations

import pytest

from intruder.pipeline.trf.subset_vcf_by_novelty import NOVEL, novel_loci, subset

HEADER = (
    "##fileformat=VCFv4.2\n"
    '##FORMAT=<ID=CO,Number=1,Type=String,Description="breakpoint">\n'
    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
)


def write(path, text):
    path.write_text(text)
    return str(path)


def vcf(tmp_path, records):
    return write(tmp_path / "in.vcf", HEADER + "".join(records))


def table(tmp_path, rows, columns=("chrom", "ins_coord", "SVID", "novelty", "filter")):
    body = "\t".join(columns) + "\n"
    body += "".join("\t".join(str(r[c]) for c in columns) + "\n" for r in rows)
    return write(tmp_path / "novelty.tsv", body)


def row(chrom="chr1", pos="100", svid="Sniffles2.INS.1S0",
        novelty="novel_motif", filt="PASS"):
    return {"chrom": chrom, "ins_coord": pos, "SVID": svid,
            "novelty": novelty, "filter": filt}


def test_a_locus_is_selected_by_coordinate_not_by_svid(tmp_path):
    """The table's SVID is the per-sample Sniffles ID, not the record's ID.

    On the real data only 160 of 208 novel SVIDs appeared in the VCF's ID column
    at all, so an ID join silently dropped a quarter of the novel loci.
    """
    v = vcf(tmp_path, ["chr1\t100\tSOME.OTHER.ID\tG\tGAA\t.\t.\t.\tCO\t1\n"])
    t = table(tmp_path, [row(chrom="chr1", pos="100", svid="Sniffles2.INS.9S0")])
    kept, total, matched = subset(v, str(tmp_path / "out.vcf"), novel_loci(t))
    assert (kept, total, matched) == (1, 1, 1)


def test_a_reused_vcf_id_does_not_drag_in_an_unrelated_locus(tmp_path):
    """A SURVIVOR merge reuses the first sample's ID: 500 records, 227 IDs.

    Selecting on that string also pulled in every other locus sharing it.
    """
    v = vcf(tmp_path, [
        "chr1\t100\tSniffles2.INS.1S0\tG\tGAA\t.\t.\t.\tCO\t1\n",
        "chr5\t999\tSniffles2.INS.1S0\tG\tGTT\t.\t.\t.\tCO\t1\n",  # same ID, other locus
    ])
    t = table(tmp_path, [row(chrom="chr1", pos="100")])
    out = str(tmp_path / "out.vcf")
    kept, total, _ = subset(v, out, novel_loci(t))
    assert (kept, total) == (1, 2)
    with open(out) as fh:
        assert "chr5" not in fh.read()


def test_every_sample_at_a_novel_locus_is_kept_even_the_known_rows(tmp_path):
    """The screen is per (locus, sample, TRF call); the embedding needs them all.

    Keeping only the novel rows would leave a locus whose embedded alleles are
    exactly the unusual ones, which is not comparable to anything.
    """
    t = table(tmp_path, [
        row(pos="100", svid="a", novelty="novel_motif"),
        row(pos="100", svid="b", novelty="known"),
    ])
    assert novel_loci(t) == {("chr1", "100")}


def test_a_locus_that_is_only_ever_known_is_not_selected(tmp_path):
    t = table(tmp_path, [row(pos="100", novelty="known")])
    assert novel_loci(t) == set()


def test_non_pass_rows_are_ignored_unless_asked_for(tmp_path):
    """The purity filters dominate the novelty result, so PASS is the default."""
    t = table(tmp_path, [row(pos="100", novelty="novel_locus", filt="low_purity")])
    assert novel_loci(t) == set()
    assert novel_loci(t, require_pass=False) == {("chr1", "100")}


def test_a_table_without_a_filter_column_is_not_silently_empty(tmp_path):
    """An unfiltered novelty.tsv has no `filter` column; requiring PASS on it
    would drop every row and look identical to "nothing was novel"."""
    t = table(tmp_path, [row(pos="100")],
              columns=("chrom", "ins_coord", "SVID", "novelty"))
    assert novel_loci(t, require_pass=True) == {("chr1", "100")}


def test_verdicts_are_selectable(tmp_path):
    t = table(tmp_path, [
        row(pos="100", novelty="novel_motif"),
        row(pos="200", novelty="novel_locus"),
    ])
    assert novel_loci(t) == {("chr1", "100"), ("chr1", "200")}
    assert novel_loci(t, verdicts=("novel_locus",)) == {("chr1", "200")}


def test_the_header_survives_because_loci_reads_format_from_it(tmp_path):
    """evo.embeddings.loci reads per-sample ID/RAL/AAL/LN/CO out of the header;
    a subset that dropped it would parse as a VCF with no calls in it."""
    v = vcf(tmp_path, ["chr1\t100\tx\tG\tGAA\t.\t.\t.\tCO\t1\n"])
    out = str(tmp_path / "out.vcf")
    subset(v, out, {("chr1", "100")})
    with open(out) as fh:
        text = fh.read()
    assert text.startswith("##fileformat=VCFv4.2")
    assert "##FORMAT=<ID=CO" in text and "#CHROM\tPOS\tID" in text


def test_one_coordinate_may_name_several_records_and_all_are_kept(tmp_path):
    """24 coordinates are duplicated in the real VCF; they are the same locus."""
    v = vcf(tmp_path, [
        "chr1\t100\ta\tG\tGAA\t.\t.\t.\tCO\t1\n",
        "chr1\t100\tb\tG\tGTT\t.\t.\t.\tCO\t1\n",
    ])
    kept, total, matched = subset(v, str(tmp_path / "out.vcf"), {("chr1", "100")})
    assert (kept, total, matched) == (2, 2, 1)


def test_loci_absent_from_the_vcf_are_countable_by_the_caller(tmp_path):
    """`matched` is what lets main() warn that the two files are from different
    runs, instead of that showing up later as a short embedding matrix."""
    v = vcf(tmp_path, ["chr1\t100\ta\tG\tGAA\t.\t.\t.\tCO\t1\n"])
    keep = {("chr1", "100"), ("chr9", "777")}
    kept, _, matched = subset(v, str(tmp_path / "out.vcf"), keep)
    assert kept == 1 and matched == 1 and len(keep) - matched == 1


def test_a_table_that_is_not_a_novelty_table_says_so(tmp_path):
    t = write(tmp_path / "novelty.tsv", "chrom\tstart\tend\nchr1\t1\t2\n")
    with pytest.raises(SystemExit, match="novelty"):
        novel_loci(t)


def test_novel_names_both_verdicts_and_not_known(tmp_path):
    assert set(NOVEL) == {"novel_motif", "novel_locus"}
