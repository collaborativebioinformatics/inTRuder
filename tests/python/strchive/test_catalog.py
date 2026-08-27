"""Parsing and indexing the STRchive catalog."""

from __future__ import annotations

import json

import pytest

from strchive.catalog import Catalog


def test_loads_every_fixture_locus(catalog):
    assert len(catalog) == 5
    assert {locus.id for locus in catalog} == {
        "OPDM5_ABCD3", "CANVAS_RFC1", "SCA37_DAB1", "HMNR7_VWA1", "FAME1_SAMD12",
    }


def test_coordinates_are_taken_verbatim_from_the_build(catalog, catalog_hg19, fixture_path):
    """STRchive coordinates are BED style, so they are stored unshifted."""
    records = {r["id"]: r for r in json.loads(fixture_path.read_text())}
    for locus in catalog:
        assert (locus.start, locus.end) == (
            records[locus.id]["start_hg38"], records[locus.id]["stop_hg38"])
    for locus in catalog_hg19:
        assert (locus.start, locus.end) == (
            records[locus.id]["start_hg19"], records[locus.id]["stop_hg19"])


def test_builds_disagree(catalog, catalog_hg19):
    """A wrong --build silently shifts everything, so make sure they differ."""
    hg38 = catalog.by_id("CANVAS_RFC1")
    hg19 = catalog_hg19.by_id("CANVAS_RFC1")
    assert hg38.start != hg19.start
    assert hg38.chrom == hg19.chrom


def test_unknown_build_is_rejected(fixture_path):
    with pytest.raises(ValueError, match="unknown build"):
        Catalog.from_file(fixture_path, build="hg17")


def test_motifs_are_split_by_class(catalog):
    rfc1 = catalog.by_id("CANVAS_RFC1")
    assert rfc1.motifs["reference"] == ("AAAAG",)
    assert set(rfc1.motifs["pathogenic"]) == {"AAGGG", "ACAGG", "AAAGG", "CAGGG"}
    assert rfc1.novel == "novel"      # pathogenic motif is absent from hg38


def test_missing_fields_become_none_not_zero(catalog):
    vwa1 = catalog.by_id("HMNR7_VWA1")
    assert vwa1.ref_copies is None
    dab1 = catalog.by_id("SCA37_DAB1")
    assert dab1.ref_copies == 0.0     # present and zero, not missing


def test_by_id_returns_none_when_absent(catalog):
    assert catalog.by_id("NOT_A_LOCUS") is None


# --------------------------------------------------------------------------- #
# lookup
# --------------------------------------------------------------------------- #

def test_distance_to_delegates_to_the_shared_rule(catalog):
    """The maths is trcore's and tested there; this checks the wiring."""
    abcd3 = catalog.by_id("OPDM5_ABCD3")
    assert abcd3.distance_to(abcd3.start, abcd3.start + 1) == 0
    assert abcd3.distance_to(abcd3.end - 1, abcd3.end) == 0
    assert abcd3.distance_to(abcd3.end, abcd3.end + 1) == 1
    assert abcd3.distance_to(abcd3.start - 1, abcd3.start) == 1
    assert abcd3.distance_to(abcd3.end + 9, abcd3.end + 10) == 10


def test_nearby_respects_the_window(catalog):
    abcd3 = catalog.by_id("OPDM5_ABCD3")
    just_outside = abcd3.end + 50
    assert catalog.nearby("chr1", just_outside, just_outside + 1, window=0) == []
    assert catalog.nearby("chr1", just_outside, just_outside + 1, window=100) == [abcd3]


def test_nearby_returns_nearest_first(catalog):
    # chr1 carries three fixture loci; ask with a window wide enough for all.
    hits = catalog.nearby("chr1", 94418430, 94418431, window=100_000_000)
    assert [h.id for h in hits] == ["OPDM5_ABCD3", "SCA37_DAB1", "HMNR7_VWA1"]


def test_nearby_accepts_unprefixed_contigs(catalog):
    assert catalog.nearby("4", 39348430, 39348431) == catalog.nearby("chr4", 39348430, 39348431)


def test_nearby_on_an_absent_contig_is_empty(catalog):
    assert catalog.nearby("chr21", 1, 2, window=10_000) == []


# --------------------------------------------------------------------------- #
# allele ranges
# --------------------------------------------------------------------------- #

def test_allele_class_uses_the_pathogenic_range(catalog):
    abcd3 = catalog.by_id("OPDM5_ABCD3")    # benign 3-44, pathogenic 118-694
    assert abcd3.allele_class(10) == "benign"
    assert abcd3.allele_class(200) == "pathogenic"
    assert abcd3.allele_class(118) == "pathogenic"      # inclusive lower bound
    assert abcd3.allele_class(694) == "pathogenic"      # inclusive upper bound
    assert abcd3.allele_class(80) == "unknown"          # gap between the ranges
    assert abcd3.allele_class(None) == "unknown"


def test_allele_class_prefers_pathogenic_where_ranges_overlap(catalog):
    rfc1 = catalog.by_id("CANVAS_RFC1")     # benign 0-11, intermediate 11-200
    assert rfc1.allele_class(11) == "intermediate"
    assert rfc1.allele_class(5) == "benign"
    assert rfc1.allele_class(500) == "pathogenic"


def test_allele_class_with_a_half_open_range(catalog):
    samd12 = catalog.by_id("FAME1_SAMD12")  # no benign range, pathogenic_min 105
    assert samd12.allele_class(500) == "pathogenic"
    assert samd12.allele_class(10) == "unknown"
