"""The three questions ``compare`` answers: locus, motif, allele."""

from __future__ import annotations

import pytest

from intruder.pipeline.strchive.compare import (
    OUTPUT_COLUMNS,
    Query,
    as_row,
    classify_motif,
    compare,
)

# Real hg38 coordinates from the fixture loci.
ABCD3 = ("chr1", 94418430)          # locus chr1:94418421-94418444, CCG, path >= 118
RFC1 = ("chr4", 39348430)           # locus chr4:39348424-39348483, ref AAAAG, path AAGGG
VWA1 = ("chr1", 1435800)            # ref and pathogenic motifs are rotations


def q(chrom, pos, motif, **kwargs) -> Query:
    return Query.from_point(chrom, pos, motif, **kwargs)


# --------------------------------------------------------------------------- #
# coordinates
# --------------------------------------------------------------------------- #

def test_from_point_converts_vcf_coordinates():
    """VCF POS is 1-based; the catalog is 0-based half-open."""
    assert q("chr1", 100, "AT").start == 99
    assert q("chr1", 100, "AT", coord_base=0).start == 100
    assert q("chr1", 100, "AT").end == 100


def test_from_point_normalizes_the_contig():
    assert q("1", 100, "AT").chrom == "chr1"


def test_a_one_base_offset_still_lands_on_the_locus(catalog):
    """The first and last base of a locus must both count as overlapping."""
    first = compare(q("chr1", 94418421 + 1, "CCG"), catalog)   # 1-based POS of locus start
    last = compare(q("chr1", 94418444, "CCG"), catalog)        # 1-based POS of locus end
    assert first.distance == 0 and last.distance == 0
    outside = compare(q("chr1", 94418445, "CCG"), catalog)
    assert outside.status == "no_locus_match"


# --------------------------------------------------------------------------- #
# question 1: locus
# --------------------------------------------------------------------------- #

def test_no_locus_match_is_the_common_case(catalog):
    match = compare(q("chr1", 66378, "TATAT"), catalog)
    assert match.status == "no_locus_match"
    assert match.locus is None and match.n_nearby == 0
    assert not match.is_hit


def test_window_widens_the_search(catalog):
    just_past = compare(q("chr1", 94418544, "CCG"), catalog)
    assert just_past.status == "no_locus_match"
    with_window = compare(q("chr1", 94418544, "CCG"), catalog, window=200)
    assert with_window.is_hit and with_window.distance == 100


def test_wrong_contig_never_matches(catalog):
    assert compare(q("chr2", 94418430, "CCG"), catalog, window=10_000).status == "no_locus_match"


# --------------------------------------------------------------------------- #
# question 2: motif
# --------------------------------------------------------------------------- #

def test_pathogenic_motif_is_recognised(catalog):
    match = compare(q(*RFC1, "AAGGG", rep_units=500), catalog)
    assert match.locus.id == "CANVAS_RFC1"
    assert match.motif_class == "pathogenic"
    assert match.matched_motif == "AAGGG"
    assert match.motif_edits == 0


def test_reference_motif_at_the_same_locus_is_not_pathogenic(catalog):
    """RFC1 expansion is only pathogenic with a non-reference motif."""
    match = compare(q(*RFC1, "AAAAG", rep_units=500), catalog)
    assert match.motif_class == "reference"
    assert match.status == "locus_known_motif"


def test_motif_matching_is_strand_and_phase_independent(catalog):
    for motif in ("AAGGG", "GGGAA", "CCCTT"):      # rotations and the reverse complement
        match = compare(q(*RFC1, motif, rep_units=500), catalog)
        assert match.motif_class == "pathogenic", motif


def test_stranded_mode_rejects_the_reverse_complement(catalog):
    assert compare(q(*RFC1, "CCCTT"), catalog, stranded=True).motif_class == "none"
    assert compare(q(*RFC1, "GGGAA"), catalog, stranded=True).motif_class == "pathogenic"


def test_an_uncatalogued_motif_at_a_known_locus_is_the_novel_case(catalog):
    match = compare(q(*ABCD3, "AATTG", rep_units=40), catalog)
    assert match.status == "locus_novel_motif"
    assert match.is_hit
    assert match.motif_class == "none"
    assert match.motif_edits is None and match.matched_motif == ""


def test_near_miss_motifs_need_an_explicit_budget(catalog):
    """One substitution away from AAGGG is not a match unless asked for."""
    assert compare(q(*RFC1, "AATGG"), catalog).motif_class == "none"
    fuzzy = compare(q(*RFC1, "AATGG"), catalog, max_motif_edits=1)
    assert fuzzy.motif_class == "pathogenic" and fuzzy.motif_edits == 1


def test_pathogenic_wins_when_a_motif_is_in_two_classes(catalog):
    """VWA1 lists the same unit as both reference and pathogenic."""
    cls, edits, _ = classify_motif("GGCGCGGAGC", catalog.by_id("HMNR7_VWA1"))
    assert cls == "pathogenic" and edits == 0


def test_empty_motif_matches_nothing(catalog):
    assert compare(q(*ABCD3, ""), catalog).motif_class == "none"


# --------------------------------------------------------------------------- #
# question 3: allele
# --------------------------------------------------------------------------- #

def test_estimated_copies_add_to_the_reference(catalog):
    """The insertion is called against the reference, so its copies are extra."""
    match = compare(q(*ABCD3, "CCG", rep_units=120), catalog)
    assert match.est_copies == pytest.approx(7.7 + 120)
    assert match.allele_class == "pathogenic"
    assert match.status == "pathogenic_expansion"


def test_pathogenic_motif_below_the_range_is_not_an_expansion(catalog):
    match = compare(q(*ABCD3, "CCG", rep_units=10), catalog)
    assert match.allele_class == "benign"
    assert match.status == "pathogenic_motif"


def test_copies_are_unknown_without_rep_units(catalog):
    match = compare(q(*ABCD3, "CCG"), catalog)
    assert match.est_copies is None
    assert match.allele_class == "unknown"
    assert match.status == "pathogenic_motif"


def test_copies_are_unknown_when_the_locus_has_no_ref_copies(catalog):
    match = compare(q(*VWA1, "GGCGCGGAGC", rep_units=50), catalog)
    assert match.locus.id == "HMNR7_VWA1"
    assert match.locus.ref_copies is None
    assert match.est_copies is None and match.allele_class == "unknown"


def test_zero_ref_copies_still_produces_an_estimate(catalog):
    """SCA37_DAB1 has ref_copies 0.0 -- falsy, but not missing."""
    match = compare(q("chr1", 57367050, "TGAAA", rep_units=40), catalog)
    assert match.locus.id == "SCA37_DAB1"
    assert match.est_copies == pytest.approx(40.0)
    assert match.allele_class == "pathogenic"


# --------------------------------------------------------------------------- #
# gene cross-check
# --------------------------------------------------------------------------- #

def test_gene_is_reported_not_matched_on(catalog):
    """A disagreeing gene is surfaced, never used to reject the locus."""
    match = compare(q(*ABCD3, "CCG", gene="WRONG1", rep_units=120), catalog)
    assert match.is_hit
    assert match.gene_agrees is False
    assert match.status == "pathogenic_expansion"


def test_gene_agreement_is_case_insensitive(catalog):
    assert compare(q(*ABCD3, "CCG", gene="abcd3"), catalog).gene_agrees is True


def test_gene_agreement_is_none_without_a_gene(catalog):
    assert compare(q(*ABCD3, "CCG"), catalog).gene_agrees is None
    assert compare(q("chr1", 66378, "TATAT", gene="ABCD3"), catalog).gene_agrees is None


# --------------------------------------------------------------------------- #
# choosing among nearby loci
# --------------------------------------------------------------------------- #

def test_a_motif_match_outranks_a_closer_motif_less_locus(catalog):
    """With a huge window every chr1 locus is in play; the motif decides."""
    match = compare(q("chr1", 1435900, "CCG", rep_units=120), catalog, window=100_000_000)
    assert match.n_nearby == 3
    assert match.locus.id == "OPDM5_ABCD3"      # not the much nearer HMNR7_VWA1
    assert match.motif_class == "pathogenic"


def test_proximity_decides_when_no_motif_matches(catalog):
    match = compare(q("chr1", 1435900, "AATTG"), catalog, window=100_000_000)
    assert match.locus.id == "HMNR7_VWA1"       # nearest
    assert match.status == "locus_novel_motif"


# --------------------------------------------------------------------------- #
# row rendering
# --------------------------------------------------------------------------- #

def test_as_row_fills_every_column(catalog):
    match = compare(q(*ABCD3, "CCG", gene="ABCD3", rep_units=120), catalog)
    row = as_row(match, catalog)
    assert set(row) == set(OUTPUT_COLUMNS)
    assert row["strchive_status"] == "pathogenic_expansion"
    assert row["strchive_id"] == "OPDM5_ABCD3"
    assert row["strchive_est_copies"] == "127.7"
    assert row["strchive_gene_agrees"] == "true"
    assert row["strchive_novel_in_ref"] == "ref"
    assert row["strchive_catalog"] == "STRchive v2.26.0-test (hg38)"


def test_as_row_fills_every_column_on_a_miss(catalog):
    row = as_row(compare(q("chr1", 66378, "TATAT"), catalog), catalog)
    assert set(row) == set(OUTPUT_COLUMNS)
    assert row["strchive_status"] == "no_locus_match"
    assert row["strchive_id"] == ""
    assert row["strchive_n_nearby"] == "0"
    assert row["strchive_catalog"] == "STRchive v2.26.0-test (hg38)"


def test_as_row_never_writes_none(catalog):
    for match in (compare(q(*VWA1, "GGCGCGGAGC"), catalog),
                  compare(q(*ABCD3, "AATTG"), catalog),
                  compare(q("chr1", 66378, "TATAT"), catalog)):
        row = as_row(match, catalog)
        assert all(isinstance(v, str) for v in row.values())
        assert "None" not in row.values()
