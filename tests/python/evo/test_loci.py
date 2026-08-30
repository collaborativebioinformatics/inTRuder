"""Reading per-sample insertion alleles out of a merged SV VCF."""

from __future__ import annotations

import pytest

from evo.embeddings import insertion_sequence, parse_co, read_insertions

HEADER = """\
##fileformat=VCFv4.1
##INFO=<ID=SVTYPE,Number=1,Type=String,Description="Type">
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\tS2\tS3
"""

FMT = "GT:LN:ID:RAL:AAL:CO"


def vcf(tmp_path, *rows):
    p = tmp_path / "t.vcf"
    p.write_text(HEADER + "".join(rows))
    return str(p)


def record(pos, info, *cells):
    return f"chr1\t{pos}\tREC\tG\tGAAA\t.\tPASS\t{info}\t{FMT}\t" + "\t".join(cells) + "\n"


def called(ln, svid, ral, aal, co):
    return f"0/1:{ln}:{svid}:{ral}:{aal}:{co}"


UNCALLED = "./.:0:NaN:NAN:NAN:NAN"


# --- insertion_sequence -------------------------------------------------------

def test_strips_this_samples_anchor_not_the_sample_count():
    """The bug this module exists to avoid: stripping len(array) not len(RAL[s])."""
    assert insertion_sequence("G", "GAAAA") == "AAAA"


@pytest.mark.parametrize("ral,aal,expected", [
    ("G", "GAAA", "AAA"),
    ("GC", "GCTTT", "TTT"),      # multi-base anchors occur in merged VCFs
    ("G", "G", ""),              # no inserted bases
])
def test_insertion_sequence(ral, aal, expected):
    assert insertion_sequence(ral, aal) == expected


def test_malformed_pair_is_left_intact_rather_than_mis_split():
    """AAL not starting with RAL means a broken record; guessing an offset there
    would silently shift every downstream coordinate."""
    assert insertion_sequence("G", "TTTT") == "TTTT"


# --- parse_co -----------------------------------------------------------------

def test_parse_co_takes_the_left_breakpoint():
    assert parse_co("chr1_10712-chr1_10712") == ("chr1", 10712)


def test_parse_co_splits_on_the_last_underscore():
    """Contig names contain underscores; splitting on the first loses them."""
    assert parse_co("chr14_GL000009v2_random_500-chr14_GL000009v2_random_500") == (
        "chr14_GL000009v2_random",
        500,
    )


@pytest.mark.parametrize("bad", ["NAN", "", "chr1_", "garbage"])
def test_parse_co_rejects_junk(bad):
    assert parse_co(bad) is None


# --- read_insertions ----------------------------------------------------------

def test_breakpoint_comes_from_co_not_the_record(tmp_path):
    """The whole reason this module reads FORMAT: 59% of real per-sample entries
    sit at a non-zero offset from the record POS, median 34 bp."""
    p = vcf(tmp_path, record(
        1000, "SVTYPE=INS",
        called(3, "S.1", "G", "GAAA", "chr1_940-chr1_940"), UNCALLED, UNCALLED,
    ))
    (c,) = read_insertions(p)
    assert (c.pos, c.record_pos) == (940, 1000)
    assert c.insert == "AAA"


def test_each_called_sample_yields_its_own_allele(tmp_path):
    """324/500 real records carry more than one distinct AAL; collapsing them to
    the record ALT would throw that away."""
    p = vcf(tmp_path, record(
        1000, "SVTYPE=INS",
        called(3, "S.1", "G", "GAAA", "chr1_1000-chr1_1000"),
        called(5, "S.2", "G", "GTTTTT", "chr1_1002-chr1_1002"),
        UNCALLED,
    ))
    calls = list(read_insertions(p))
    assert [(c.sample, c.insert, c.pos) for c in calls] == [
        ("S1", "AAA", 1000),
        ("S2", "TTTTT", 1002),
    ]


def test_uncalled_samples_are_skipped(tmp_path):
    p = vcf(tmp_path, record(
        1000, "SVTYPE=INS",
        UNCALLED, called(3, "S.1", "G", "GAAA", "chr1_1000-chr1_1000"), UNCALLED,
    ))
    assert [c.sample for c in read_insertions(p)] == ["S2"]


def test_svid_is_the_per_sample_id(tmp_path):
    """Record IDs repeat across loci in a merged VCF, so the per-sample ID is
    what joins back to sv_trfcaller output."""
    p = vcf(tmp_path, record(
        1000, "SVTYPE=INS",
        called(3, "Sniffles2.INS.7S0", "G", "GAAA", "chr1_1000-chr1_1000"),
        UNCALLED, UNCALLED,
    ))
    (c,) = read_insertions(p)
    assert c.svid == "Sniffles2.INS.7S0"


def test_non_insertions_are_ignored(tmp_path):
    p = vcf(tmp_path,
        record(1000, "SVTYPE=DEL",
               called(3, "S.1", "G", "GAAA", "chr1_1000-chr1_1000"), UNCALLED, UNCALLED),
        record(2000, "SVTYPE=INS",
               called(3, "S.2", "G", "GCCC", "chr1_2000-chr1_2000"), UNCALLED, UNCALLED),
    )
    assert [c.record_pos for c in read_insertions(p)] == [2000]


def test_length_disagreement_is_reported_not_hidden(tmp_path):
    p = vcf(tmp_path, record(
        1000, "SVTYPE=INS",
        called(99, "S.1", "G", "GAAA", "chr1_1000-chr1_1000"), UNCALLED, UNCALLED,
    ))
    (c,) = read_insertions(p)
    assert c.declared_length == 99
    assert not c.length_agrees


def test_empty_insertion_is_dropped(tmp_path):
    p = vcf(tmp_path, record(
        1000, "SVTYPE=INS",
        called(0, "S.1", "G", "G", "chr1_1000-chr1_1000"), UNCALLED, UNCALLED,
    ))
    assert list(read_insertions(p)) == []
