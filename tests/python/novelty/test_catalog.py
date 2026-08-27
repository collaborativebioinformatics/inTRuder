"""The interval index and the known/novel verdict."""

from __future__ import annotations

import pandas as pd
import pytest

from novelty.catalog import STATUSES, RepeatCatalog
from trcore.coords import to_external, to_internal
from trcore.motifs import MotifEquivalence, MotifTolerance

# --------------------------------------------------------------------------- #
# coordinates -- the part that silently breaks if 0/1-based is mixed up
# --------------------------------------------------------------------------- #

def test_coordinate_round_trip():
    # A 1-based VCF POS of 10001 is the base at 0-based offset 10000.
    assert to_internal(10001, coord_base=1) == 10000
    assert to_internal(10000, coord_base=0) == 10000
    # simpleRepeat [10000, 10468) is 1-based 10001..10468.
    assert to_external(10000, 10468, coord_base=1) == (10001, 10468)
    assert to_external(10000, 10468, coord_base=0) == (10000, 10468)


# --------------------------------------------------------------------------- #
# index + overlap search
# --------------------------------------------------------------------------- #

def test_overlapping_boundaries(catalog):
    # chr1:[10000, 10468) -- half-open, so 10467 is inside and 10468 is not.
    assert len(catalog.overlapping("chr1", 10000, 10001)) == 1
    assert len(catalog.overlapping("chr1", 10467, 10468)) == 1
    assert len(catalog.overlapping("chr1", 10468, 10469)) == 0
    assert len(catalog.overlapping("chr1", 9999, 10000)) == 0
    # Spanning both chr1 rows requires a query that reaches them both.
    assert len(catalog.overlapping("chr1", 10000, 20001)) == 2
    # Unknown contigs are simply empty, not an error.
    assert catalog.overlapping("chrZZ", 0, 1000) == []


def test_overlapping_is_sorted_and_chrom_scoped(catalog):
    hits = catalog.overlapping("chr1", 0, 10**6)
    assert [h.start for h in hits] == [10000, 20000]
    assert all(h.chrom == "chr1" for h in hits)
    assert [h.start for h in catalog.overlapping("chr2", 0, 10**6)] == [500]


def test_overlapping_finds_a_repeat_nested_inside_another(write_bed):
    """A short repeat inside a long one starts later but must still be found."""
    index = RepeatCatalog.from_file(write_bed(rows=[
        ("chr1", 100, 100000, "AT"),
        ("chr1", 200, 300, "CAG"),
    ]), verbose=False, cache=False)
    assert {h.motif for h in index.overlapping("chr1", 50000, 50001)} == {"AT"}
    assert {h.motif for h in index.overlapping("chr1", 250, 251)} == {"AT", "CAG"}


def test_record_fields_are_read_from_the_right_columns(catalog):
    (repeat,) = catalog.overlapping("chr1", 10000, 10001)
    assert (repeat.start, repeat.end) == (10000, 10468)
    assert repeat.length == 468
    assert repeat.motif == "TAACCC"
    assert repeat.annotations == {"period": 6, "copy_num": pytest.approx(77.2, abs=0.01),
                                  "consensus_size": 6, "per_match": 95, "per_indel": 3}


def test_a_bed_catalog_simply_has_no_annotations(write_bed):
    index = RepeatCatalog.from_file(write_bed(), platform="trexplorer",
                                    verbose=False, cache=False)
    assert index.annotations == ()
    assert index.overlapping("chr1", 10000, 10001)[0].annotations == {}


# --------------------------------------------------------------------------- #
# screening
# --------------------------------------------------------------------------- #

def test_known_motif_inside_annotated_repeat(catalog):
    verdict = catalog.screen("chr1", 10100, "TAACCC", window=10)
    assert verdict.status == "known"
    assert not verdict.is_novel
    assert verdict.best.distance == 0
    assert verdict.best.motif_edits == 0


def test_known_motif_matches_any_rotation(catalog):
    """Every phase of the reference TAACCC repeat answers the query."""
    for phase in ("TAACCC", "AACCCT", "ACCCTA", "CCCTAA", "CCTAAC", "CTAACC"):
        assert catalog.screen("chr1", 10100, phase, window=10).status == "known", phase
    # But the opposite strand does not, unless the catalogue was built for it.
    assert catalog.screen("chr1", 10100, "GGGTTA", window=10).status == "novel_motif"


def test_novel_motif_at_a_known_locus(catalog):
    verdict = catalog.screen("chr1", 10100, "CAG", window=10)
    assert verdict.status == "novel_motif"
    assert verdict.is_novel
    assert verdict.n_nearby == 1
    assert verdict.best.repeat.motif == "TAACCC"   # the nearest, not a match


def test_novel_locus_when_nothing_is_annotated(catalog):
    verdict = catalog.screen("chr1", 500000, "CAG", window=10)
    assert verdict.status == "novel_locus"
    assert verdict.n_nearby == 0
    assert verdict.best is None


def test_window_controls_how_far_a_repeat_may_be(catalog):
    # 5bp past the end of chr1:[10000, 10468).
    assert catalog.screen("chr1", 10472, "TAACCC", window=0).status == "novel_locus"
    assert catalog.screen("chr1", 10472, "TAACCC", window=4).status == "novel_locus"
    assert catalog.screen("chr1", 10472, "TAACCC", window=5).status == "known"
    assert catalog.screen("chr1", 10472, "TAACCC", window=50).best.distance == 5


def test_window_one_covers_the_off_by_one_at_a_repeat_edge(catalog):
    # Exactly one base past the last base of the repeat.
    assert catalog.screen("chr1", 10468, "TAACCC", window=0).status == "novel_locus"
    verdict = catalog.screen("chr1", 10468, "TAACCC", window=1)
    assert verdict.status == "known"
    assert verdict.best.distance == 1


def test_max_motif_edits_accepts_near_misses(catalog):
    # TAACCA is one substitution from TAACCC.
    assert catalog.screen("chr1", 10100, "TAACCA", window=10).status == "novel_motif"
    verdict = catalog.screen("chr1", 10100, "TAACCA", window=10,
                             tolerance=MotifTolerance(max_edits=1))
    assert verdict.status == "known"
    assert verdict.best.motif_edits == 1


def test_best_hit_prefers_a_motif_match_over_a_closer_repeat(write_simplerepeat):
    rows = [
        (585, "chr3", 100, 200, "trf", 3, 33.0, 3, 99, 0, 100, 0, 0, 0, 0, 1.0, "CAG"),
        (585, "chr3", 205, 300, "trf", 2, 47.0, 2, 99, 0, 100, 0, 0, 0, 0, 1.0, "AT"),
    ]
    index = RepeatCatalog.from_file(write_simplerepeat(rows), platform="ucsc",
                                    verbose=False, cache=False)
    # The point sits in the AT repeat, but the CAG repeat is within the window.
    verdict = index.screen("chr3", 210, "CAG", window=20)
    assert verdict.status == "known"
    assert verdict.n_nearby == 2
    assert verdict.best.repeat.motif == "CAG"


def test_the_default_index_keeps_reverse_complement_novel(write_simplerepeat):
    """Out of the box the reference TAACCC repeat does not answer a GGGTTA query."""
    index = RepeatCatalog.from_file(write_simplerepeat(), platform="ucsc",
                                    verbose=False, cache=False)
    assert index.screen("chr1", 10100, "TAACCC", window=10).status == "known"
    assert index.screen("chr1", 10100, "AACCCT", window=10).status == "known"
    assert index.screen("chr1", 10100, "GGGTTA", window=10).status == "novel_motif"


def test_reverse_complement_index_calls_the_other_strand_known(write_simplerepeat):
    index = RepeatCatalog.from_file(
        write_simplerepeat(), platform="ucsc", verbose=False, cache=False,
        equivalence=MotifEquivalence(reverse_complement=True))
    assert index.screen("chr1", 10100, "GGGTTA", window=10).status == "known"


def test_reverse_complement_bp_gates_the_strand_fold(write_simplerepeat):
    """TAACCC is 6bp, so a 7bp threshold leaves its reverse complement novel."""
    at_six = RepeatCatalog.from_file(
        write_simplerepeat(), platform="ucsc", verbose=False, cache=False,
        equivalence=MotifEquivalence(reverse_complement=True,
                                     reverse_complement_bp=6))
    at_seven = RepeatCatalog.from_file(
        write_simplerepeat(), platform="ucsc", verbose=False, cache=False,
        equivalence=MotifEquivalence(reverse_complement=True,
                                     reverse_complement_bp=7))
    assert at_six.screen("chr1", 10100, "GGGTTA", window=10).status == "known"
    assert at_seven.screen("chr1", 10100, "GGGTTA", window=10).status == "novel_motif"


def test_no_circular_index_requires_the_same_phase(write_simplerepeat):
    index = RepeatCatalog.from_file(
        write_simplerepeat(), platform="ucsc", verbose=False, cache=False,
        equivalence=MotifEquivalence(circular=False))
    assert index.screen("chr1", 10100, "TAACCC", window=10).status == "known"
    assert index.screen("chr1", 10100, "AACCCT", window=10).status == "novel_motif"


def test_screen_normalizes_input_contig_names(catalog):
    assert catalog.screen("1", 10100, "TAACCC", window=10).status == "known"


# --------------------------------------------------------------------------- #
# batch screening
# --------------------------------------------------------------------------- #

def test_screen_frame_agrees_with_screen_row_by_row(catalog):
    queries = [
        ("chr1", 10100, "TAACCC"),   # known
        ("chr1", 10100, "CAG"),      # novel_motif
        ("chr1", 500000, "CAG"),     # novel_locus
        ("1", 20050, "GC"),          # known, un-normalised contig
        ("chr2", 600, "AAT"),        # known, a different contig
        ("chrZZ", 1, "AT"),          # unknown contig
    ]
    frame = catalog.screen_frame([q[0] for q in queries], [q[1] for q in queries],
                                 [q[2] for q in queries], window=10)
    for row, (chrom, point, motif) in enumerate(queries):
        verdict = catalog.screen(chrom, point, motif, window=10)
        assert frame["novelty"][row] == verdict.status
        assert frame["n_nearby"][row] == verdict.n_nearby
        if verdict.best is None:
            assert frame["start"].isna()[row]
        else:
            assert frame["start"][row] == verdict.best.repeat.start
            assert frame["motif"][row] == verdict.best.repeat.motif
            assert frame["distance"][row] == verdict.best.distance


def test_screen_frame_prefixes_columns_per_platform(catalog):
    frame = catalog.screen_frame(["chr1"], [10100], ["TAACCC"], prefix="ucsc_")
    assert frame.columns[0] == "ucsc_novelty"
    assert "ucsc_per_match" in frame.columns


def test_screen_frame_omits_annotations_the_platform_lacks(write_bed):
    index = RepeatCatalog.from_file(write_bed(), verbose=False, cache=False)
    frame = index.screen_frame(["chr1"], [10100], ["TAACCC"])
    assert not [c for c in frame.columns if c in ("period", "per_match")]


def test_screen_frame_on_an_empty_input(catalog):
    assert len(catalog.screen_frame([], [], [])) == 0


# --------------------------------------------------------------------------- #
# the index cache
# --------------------------------------------------------------------------- #

def test_cache_round_trips_the_whole_index(write_simplerepeat):
    path = write_simplerepeat()
    built = RepeatCatalog.from_file(path, platform="ucsc", verbose=False)
    assert RepeatCatalog._cache_path(path).exists()

    loaded = RepeatCatalog.from_file(path, platform="ucsc", verbose=False)
    assert len(loaded) == len(built)
    assert loaded.annotations == built.annotations
    for point, motif in [(10100, "TAACCC"), (10100, "CAG"), (500000, "CAG")]:
        assert (loaded.screen("chr1", point, motif).status
                == built.screen("chr1", point, motif).status)
    (repeat,) = loaded.overlapping("chr1", 10000, 10001)
    assert repeat.motif == "TAACCC"
    assert repeat.annotations["per_match"] == 95


def test_cache_is_ignored_when_the_table_changes(write_simplerepeat, capsys):
    path = write_simplerepeat()
    RepeatCatalog.from_file(path, platform="ucsc", verbose=False)
    write_simplerepeat(rows=[
        (585, "chr1", 10000, 10468, "trf", 6, 77.2, 6, 95, 3, 789, 33, 51, 0, 15,
         1.43, "TAACCC"),
    ])
    reloaded = RepeatCatalog.from_file(path, platform="ucsc", verbose=False)
    assert len(reloaded) == 1


@pytest.mark.parametrize("equivalence", [
    MotifEquivalence(reverse_complement=True),
    MotifEquivalence(circular=False),
    MotifEquivalence(reverse_complement=True, reverse_complement_bp=7),
])
def test_cache_is_not_shared_between_equivalence_policies(write_simplerepeat,
                                                          equivalence):
    """Canonical keys are baked into the cache, so the policy is part of its key."""
    path = write_simplerepeat()
    default = RepeatCatalog.from_file(path, platform="ucsc", verbose=False)
    assert default.screen("chr1", 10100, "GGGTTA").status == "novel_motif"
    other = RepeatCatalog.from_file(path, platform="ucsc", verbose=False,
                                    equivalence=equivalence)
    assert other.equivalence == equivalence
    # Reloading under the original policy must still give the original answer.
    again = RepeatCatalog.from_file(path, platform="ucsc", verbose=False)
    assert again.screen("chr1", 10100, "GGGTTA").status == "novel_motif"


def test_cache_round_trips_the_equivalence_policy(write_simplerepeat):
    path = write_simplerepeat()
    policy = MotifEquivalence(reverse_complement=True, reverse_complement_bp=6)
    RepeatCatalog.from_file(path, platform="ucsc", verbose=False, equivalence=policy)
    reloaded = RepeatCatalog.from_file(path, platform="ucsc", verbose=False,
                                       equivalence=policy)
    assert reloaded.equivalence == policy
    assert reloaded.screen("chr1", 10100, "GGGTTA").status == "known"


def test_cache_is_not_shared_between_platforms(write_bed):
    path = write_bed()
    RepeatCatalog.from_file(path, platform="bed", verbose=False)
    other = RepeatCatalog.from_file(path, platform="trexplorer", verbose=False)
    assert other.platform == "trexplorer"


# --------------------------------------------------------------------------- #
# screening hyperparameters
# --------------------------------------------------------------------------- #

def test_max_fuzzy_motif_caps_which_motifs_are_compared(catalog):
    """Above the cap only exact canonical equality counts; near misses stay novel."""
    # TAACCA is one substitution from the annotated TAACCC, a 6bp unit.
    assert catalog.screen("chr1", 10100, "TAACCA", tolerance=MotifTolerance(
        max_edits=1, max_fuzzy_motif=6)).status == "known"
    assert catalog.screen("chr1", 10100, "TAACCA", tolerance=MotifTolerance(
        max_edits=1, max_fuzzy_motif=5)).status == "novel_motif"


def test_repeat_filter_decides_what_counts_as_annotation(catalog):
    """It changes n_nearby, not just which hit is reported."""
    from novelty.catalog import RepeatFilter

    plain = catalog.screen("chr1", 10100, "TAACCC")
    assert plain.status == "known" and plain.n_nearby == 1

    # the annotated repeat has per_match 95 and is 468bp long
    for repeat_filter in (RepeatFilter(min_identity=96),
                          RepeatFilter(min_length=500),
                          RepeatFilter(min_copy_num=100)):
        verdict = catalog.screen("chr1", 10100, "TAACCC", repeat_filter=repeat_filter)
        assert verdict.status == "novel_locus", repeat_filter
        assert verdict.n_nearby == 0
        assert verdict.best is None


def test_repeat_filter_thresholds_that_are_met_keep_the_repeat(catalog):
    from novelty.catalog import RepeatFilter
    kept = RepeatFilter(min_identity=95, min_length=468, min_copy_num=77.0)
    assert catalog.screen("chr1", 10100, "TAACCC", repeat_filter=kept).status == "known"


def test_an_empty_repeat_filter_changes_nothing(catalog):
    from novelty.catalog import RepeatFilter
    assert not RepeatFilter()
    assert (catalog.screen("chr1", 10100, "TAACCC", repeat_filter=RepeatFilter()).status
            == catalog.screen("chr1", 10100, "TAACCC").status)


def test_a_platform_without_the_column_cannot_be_filtered_on_it(write_bed):
    """BED carries no perMatch, so the threshold is reported as inapplicable."""
    from novelty.catalog import RepeatFilter

    index = RepeatCatalog.from_file(write_bed(), verbose=False, cache=False)
    repeat_filter = RepeatFilter(min_identity=96, min_length=100)
    assert repeat_filter.inapplicable(index.annotations) == ["min_identity"]
    # min_length still applies, and chr1:[10000, 10468) is long enough
    assert index.screen("chr1", 10100, "TAACCC",
                        repeat_filter=repeat_filter).status == "known"


def test_screen_frame_honours_the_repeat_filter_too(catalog):
    from novelty.catalog import RepeatFilter
    frame = catalog.screen_frame(["chr1"], [10100], ["TAACCC"],
                                 repeat_filter=RepeatFilter(min_identity=96))
    assert frame["novelty"][0] == "novel_locus"
    assert frame["n_nearby"][0] == 0


# --------------------------------------------------------------------------- #
# contig coverage
# --------------------------------------------------------------------------- #

def test_a_contig_the_catalogue_does_not_carry_is_unscreened_not_novel(catalog):
    """`novel_locus` on a contig with no rows at all would be novelty manufactured
    out of missing coverage -- TRExplorer v2 carries 25 contigs where UCSC carries
    702, and every alt/random/decoy would come back novel for free."""
    assert catalog.covers("chr1")
    assert not catalog.covers("chr1_KI270706v1_random")

    on_contig = catalog.screen("chr1", 999_999, "TAACCC")
    assert on_contig.status == "novel_locus"      # covered, nothing nearby
    assert on_contig.n_nearby == 0

    off_contig = catalog.screen("chr1_KI270706v1_random", 999_999, "TAACCC")
    assert off_contig.status == "unscreened"
    assert off_contig.n_nearby == 0


def test_covers_normalises_the_contig_name(catalog):
    assert catalog.covers("1")
    assert catalog.covers("chr1")


def test_unscreened_ranks_below_every_real_verdict():
    """So a catalogue with no opinion never overrides one that has one."""
    assert STATUSES.index("unscreened") == len(STATUSES) - 1


# --------------------------------------------------------------------------- #
# the match column
# --------------------------------------------------------------------------- #

def test_screen_frame_names_the_rule_that_accepted_the_motif(catalog):
    frame = catalog.screen_frame(["chr1", "chr1", "chr2"],
                                 [10100, 10100, 999_999],
                                 ["TAACCC", "TAACCA", "AAT"],
                                 tolerance=MotifTolerance(max_edits=1))
    assert list(frame["novelty"]) == ["known", "known", "novel_locus"]
    assert list(frame["match"][:2]) == ["exact", "fuzzy"]
    # nothing matched, so there is no rule to name -- missing, like the other
    # best-hit columns on a row with no hit
    assert pd.isna(frame["match"].iloc[2])


def test_a_subrepeat_match_is_reported_as_such(catalog):
    """An exact match must never be indistinguishable from a loosened one."""
    verdict = catalog.screen("chr1", 20050, "GCGCGT", tolerance=MotifTolerance(
        max_edits=1, min_subrepeat_motif=2))
    assert verdict.status == "known"
    assert verdict.best.match == "subrepeat"
    assert verdict.best.repeat.motif == "GC"


def test_the_best_hit_prefers_a_match_over_a_closer_non_match(catalog):
    """Ranking on the raw edit count would be wrong once a proportional budget is
    in play, because the counts are not comparable across motif lengths."""
    verdict = catalog.screen("chr1", 10100, "TAACCC", window=10_100)
    assert verdict.best.match == "exact"
    assert verdict.best.repeat.motif == "TAACCC"
