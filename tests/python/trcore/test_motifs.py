"""Motif canonicalisation -- the rule every step uses to decide two repeats match.

There is one implementation now, so there is one suite: exhaustive brute-force
rotation checks, the full equivalence/tolerance matrix, and motif pairs taken
from real pathogenic loci where the catalogues disagree on phase or strand.
"""

from __future__ import annotations

from itertools import product

import pytest

from intruder.trcore.motifs import (
    DEFAULT_EQUIVALENCE,
    DEFAULT_TOLERANCE,
    MATCH_EXACT,
    MATCH_FUZZY,
    MATCH_NONE,
    MATCH_SUBREPEAT,
    MATCH_VNTR,
    STR_MAX_MOTIF,
    MotifEquivalence,
    MotifTolerance,
    _edit_distance,
    canonical_motif,
    edit_budget,
    least_rotation,
    motif_distance,
    primitive_unit,
    reverse_complement,
    tiling_distance,
)

RC = MotifEquivalence(reverse_complement=True)
NO_ROTATION = MotifEquivalence(circular=False)
RC_ONLY = MotifEquivalence(circular=False, reverse_complement=True)


def test_reverse_complement():
    assert reverse_complement("AATG") == "CATT"
    assert reverse_complement("GC") == "GC"


@pytest.mark.parametrize("seq,expected", [
    ("AT", "AT"),
    ("ATAT", "AT"),
    ("ATATAT", "AT"),
    ("AAA", "A"),
    ("ATG", "ATG"),
    ("ATGATG", "ATG"),
    ("ATGATGA", "ATGATGA"),   # not a whole number of copies
    ("", ""),
])
def test_primitive_unit(seq, expected):
    assert primitive_unit(seq) == expected


@pytest.mark.parametrize("length", [1, 2, 3, 4, 5, 6, 7, 8])
def test_least_rotation_matches_brute_force(length):
    """Booth's algorithm must agree with the O(n^2) definition on every k-mer."""
    for tup in product("ACGT", repeat=length):
        seq = "".join(tup)
        brute = min(seq[i:] + seq[:i] for i in range(len(seq)))
        assert least_rotation(seq) == brute, seq


def test_canonical_motif_collapses_rotation_by_default():
    # All three phases of the CAG repeat are one repeat.
    assert len({canonical_motif(m) for m in ("CAG", "AGC", "GCA")}) == 1
    # A period-4 consensus that is really a 2-mer reduces to the 2-mer.
    assert canonical_motif("ATAT") == canonical_motif("AT") == "AT"
    # Genuinely different motifs stay apart.
    assert canonical_motif("AAT") != canonical_motif("AAC")


def test_reverse_complement_is_off_by_default():
    """The default must keep the two strands apart."""
    assert canonical_motif("CAG") != canonical_motif("CTG")
    assert canonical_motif("A") != canonical_motif("T")
    assert canonical_motif("AAT") != canonical_motif("ATT")
    assert canonical_motif("AC") != canonical_motif("GT")
    assert DEFAULT_EQUIVALENCE.reverse_complement is False
    assert DEFAULT_EQUIVALENCE.circular is True


def test_rotation_is_a_cyclic_shift_not_a_reversal():
    """ATC rotates to {ATC, TCA, CAT}. CTA is its *reverse*, and never matches.

    Reversing a strand is not a biological operation -- only reverse
    complementing is -- so no equivalence setting may ever admit it.
    """
    assert {canonical_motif(m) for m in ("ATC", "TCA", "CAT")} == {canonical_motif("ATC")}
    for policy in (DEFAULT_EQUIVALENCE, RC, NO_ROTATION, RC_ONLY):
        assert canonical_motif("ATC", policy) != canonical_motif("CTA", policy)
        assert motif_distance("ATC", "CTA", cutoff=0, equivalence=policy) > 0


@pytest.mark.parametrize("length", [30, 47, 100, 250])
def test_least_rotation_is_correct_for_long_units(length):
    """Booth's algorithm has to hold at VNTR lengths, not just the k-mers above.

    Long units are where rotation matters most: a caller's choice of starting
    phase is arbitrary at any length, but long units almost never agree on it.
    """
    import random
    rng = random.Random(length)
    for _ in range(50):
        seq = "".join(rng.choice("ACGT") for _ in range(length))
        assert least_rotation(seq) == min(seq[i:] + seq[:i] for i in range(len(seq)))
    # A long unit and a rotation of it are one repeat.
    unit = "TGCGACACTCACGCGGGTGCCGTCTCAGCAGCTCACGGTGTGGAAAC"
    shifted = unit[25:] + unit[:25]
    assert canonical_motif(unit) == canonical_motif(shifted)


def test_gc_and_cg_agree_by_rotation_not_by_strand():
    """A trap: GC/CG look like a strand pair but are rotations of one repeat.

    ...GCGCGC... is the same run of sequence whichever base you start on, so
    this pair collapses even with the reverse complement switched off, and only
    --no-circular separates them.
    """
    assert canonical_motif("GC") == canonical_motif("CG")
    assert canonical_motif("AT") == canonical_motif("TA")
    assert canonical_motif("GC", NO_ROTATION) != canonical_motif("CG", NO_ROTATION)


def test_reverse_complement_collapses_strands_when_enabled():
    assert canonical_motif("CAG", RC) == canonical_motif("CTG", RC)
    assert canonical_motif("A", RC) == canonical_motif("T", RC)
    assert canonical_motif("AC", RC) == canonical_motif("GT", RC)
    # With rotation on too, every phase of both strands is one repeat.
    same = ["AAT", "ATA", "TAA", "ATT", "TTA", "TAT"]
    assert len({canonical_motif(m, RC) for m in same}) == 1


def test_no_circular_keeps_the_phases_apart():
    assert canonical_motif("CAG", NO_ROTATION) != canonical_motif("AGC", NO_ROTATION)
    # Period reduction still applies -- it is not part of rotation.
    assert canonical_motif("CAGCAG", NO_ROTATION) == canonical_motif("CAG", NO_ROTATION)


def test_reverse_complement_without_rotation_pairs_only_the_exact_strands():
    """RC and rotation are independent: CTG folds in, its rotations do not."""
    assert canonical_motif("CAG", RC_ONLY) == canonical_motif("CTG", RC_ONLY)
    assert canonical_motif("CAG", RC_ONLY) != canonical_motif("AGC", RC_ONLY)
    assert canonical_motif("CAG", RC_ONLY) != canonical_motif("TGC", RC_ONLY)


@pytest.mark.parametrize("unit,rc_expected", [
    ("AC", False),        # 2bp, below the threshold: A/C strand kept apart from G/T
    ("CAG", False),       # 3bp, below: the CAG/CTG pair stays split
    ("ACCCT", False),     # 5bp, one short of the threshold
    ("TAACCC", True),     # 6bp, at the threshold: folds in with GGGTTA
    ("TAACCCA", True),    # 7bp, above it
])
def test_reverse_complement_bp_restricts_rc_to_long_enough_motifs(unit, rc_expected):
    """`>= bp` gets the reverse complement; shorter units keep their strands apart."""
    policy = MotifEquivalence(reverse_complement=True, reverse_complement_bp=6)
    rc = reverse_complement(unit)
    assert rc != unit, "test needs a unit that is not its own reverse complement"
    matched = canonical_motif(unit, policy) == canonical_motif(rc, policy)
    assert matched is rc_expected
    # Without the threshold the same pair always folds together.
    assert canonical_motif(unit, RC) == canonical_motif(rc, RC)


def test_reverse_complement_bp_is_inert_without_reverse_complement():
    policy = MotifEquivalence(reverse_complement_bp=1)
    assert canonical_motif("TAACCC", policy) != canonical_motif("GGGTTA", policy)


@pytest.mark.parametrize("a,b,expected", [
    ("AAT", "ATA", 0),      # rotation
    ("AAT", "AAC", 1),      # one substitution
    ("AATG", "AAG", 1),     # one deletion
    ("AAT", "GGC", 3),      # AAT vs GGC -- three substitutions
])
def test_motif_distance(a, b, expected):
    assert motif_distance(a, b, cutoff=3) == expected


def test_motif_distance_only_folds_in_the_strand_when_asked():
    assert motif_distance("AAT", "ATT", cutoff=3) == 1        # a near miss, not a match
    assert motif_distance("AAT", "ATT", cutoff=3, equivalence=RC) == 0


def test_motif_distance_respects_no_circular():
    assert motif_distance("CAG", "AGC", cutoff=3) == 0
    assert motif_distance("CAG", "AGC", cutoff=3, equivalence=NO_ROTATION) > 0


def test_motif_distance_beyond_cutoff_is_capped():
    """Past the cutoff the exact distance is not computed, only `cutoff + 1`."""
    assert motif_distance("AAT", "GGC", cutoff=2) == 3
    assert motif_distance("AAT", "GGC", cutoff=1) == 2


def test_motif_distance_respects_cutoff():
    assert motif_distance("AAT", "AAC", cutoff=0) == 1   # cutoff + 1
    assert motif_distance("AAT", "AAC", cutoff=1) == 1


def test_a_one_substitution_near_miss_is_not_a_match_at_cutoff_zero():
    """The case the screen must never accept by default: CAG is not CAT."""
    assert motif_distance("CAG", "CAT", cutoff=0) > 0
    assert motif_distance("CAG", "CAT", cutoff=1) == 1     # only once asked for
    for policy in (DEFAULT_EQUIVALENCE, RC, NO_ROTATION, RC_ONLY):
        assert motif_distance("CAG", "CAT", cutoff=0, equivalence=policy) > 0


# --------------------------------------------------------------------------- #
# IUPAC
# --------------------------------------------------------------------------- #

def test_reverse_complement_handles_iupac_ambiguity_codes():
    """R and Y are each other's complement; reversing without complementing them
    silently produces the wrong strand, and a catalogue is entitled to use them."""
    assert reverse_complement("ACRYN") == "NRYGT"
    assert reverse_complement("R") == "Y"
    assert reverse_complement("Y") == "R"
    assert reverse_complement("K") == "M"
    assert reverse_complement("B") == "V"
    assert reverse_complement("S") == "S"      # self-complementary
    assert reverse_complement("W") == "W"


def test_reverse_complement_is_an_involution_over_the_whole_alphabet():
    alphabet = "ACGTNRYSWKMBDHV"
    assert reverse_complement(reverse_complement(alphabet)) == alphabet


def test_reverse_complement_preserves_case():
    assert reverse_complement("acgt") == "acgt"
    assert reverse_complement("acRy") == "rYgt"


# --------------------------------------------------------------------------- #
# tolerance
# --------------------------------------------------------------------------- #

def test_edit_budget_is_flat_below_the_str_boundary():
    """A proportional budget must not reach short motifs, where one substitution
    is a real difference between two STRs."""
    short = "A" * STR_MAX_MOTIF
    assert edit_budget(short, short, 0, 0.5) == 0
    assert edit_budget(short, short, 2, 0.5) == 2      # the flat budget still applies


def test_edit_budget_scales_with_length_above_the_str_boundary():
    long = "A" * 40
    assert edit_budget(long, long, 0, 0.10) == 4
    assert edit_budget(long, long, 0, None) == 0
    # the two combine by taking the larger, so neither ever tightens the other
    assert edit_budget(long, long, 9, 0.10) == 9


def test_edit_budget_uses_the_longer_of_the_two_motifs():
    assert edit_budget("A" * 10, "A" * 40, 0, 0.10) == 4


def test_tiling_distance_counts_mismatches_in_the_best_phase():
    assert tiling_distance("AC", "ACACAC", cutoff=2) == 0
    assert tiling_distance("CA", "ACACAC", cutoff=2) == 0     # a rotation is fine
    assert tiling_distance("ACC", "ACCATC", cutoff=2) == 1


def test_tiling_distance_needs_two_whole_copies():
    """Otherwise any short unit would `tile` any long motif."""
    assert tiling_distance("ACGT", "ACGTA", cutoff=9) > 9
    assert tiling_distance("ACGT", "ACGTACGT", cutoff=9) == 0


def test_tiling_distance_caps_at_the_cutoff():
    assert tiling_distance("AAAA", "CCCCCCCC", cutoff=2) == 3


def test_default_tolerance_is_exact_only():
    assert not DEFAULT_TOLERANCE
    assert DEFAULT_TOLERANCE.compare("CAG", "AGC").kind == MATCH_EXACT
    assert DEFAULT_TOLERANCE.compare("CAG", "CAT").kind == MATCH_NONE
    assert DEFAULT_TOLERANCE.describe() == "exact canonical match only"


def test_flat_budget_reports_a_fuzzy_match():
    found = MotifTolerance(max_edits=1).compare("CAG", "CAT")
    assert (found.kind, found.edits) == (MATCH_FUZZY, 1)


def test_proportional_budget_matches_vntrs_and_leaves_strs_alone():
    """The str-analysis observation: above 6bp two catalogues rarely agree on a
    consensus, below it a substitution is a real difference."""
    tolerance = MotifTolerance(max_edit_fraction=0.10)
    query = "CGGGTGCCGTCTCAGCAGCTCACGGTGTGGAAACTGCGACACTCACA"
    target = "GTGTGGAAACTGCGACACTCACGCGGGTGCCGTCTCAGCAGCTCACG"
    assert tolerance.compare(query, target).kind == MATCH_VNTR
    assert tolerance.compare("CAG", "CAT").kind == MATCH_NONE


def test_a_flat_budget_is_named_fuzzy_even_when_the_fraction_would_also_allow_it():
    """The output should blame the tighter rule, so a 1-edit near miss does not
    read as though the VNTR budget was needed."""
    tolerance = MotifTolerance(max_edits=2, max_edit_fraction=0.5)
    found = tolerance.compare("ACGTACGTAC", "ACGTACGTAG")
    assert found.kind == MATCH_FUZZY


def test_subrepeat_accepts_a_motif_that_tiles_the_other():
    """The documented gap: TRF reports one compound unit per locus, so a query of
    ACC reads as novel against a reference consensus of ACCATC."""
    tolerance = MotifTolerance(max_edits=1, min_subrepeat_motif=3)
    found = tolerance.compare("ACC", "ACCATC")
    assert (found.kind, found.edits) == (MATCH_SUBREPEAT, 1)
    # direction does not matter: either side may be the compound one
    assert tolerance.compare("ACCATC", "ACC").kind == MATCH_SUBREPEAT


def test_subrepeat_rejects_a_degenerate_homopolymer_tiling():
    """A plain containment test would accept `A` inside almost any motif; tiling
    the whole length is what rules it out."""
    tolerance = MotifTolerance(max_edits=1, min_subrepeat_motif=1)
    assert tolerance.compare("A", "CACCACAGAAAACAGAGC").kind == MATCH_NONE


def test_subrepeat_honours_its_minimum_motif_length():
    assert MotifTolerance(max_edits=1, min_subrepeat_motif=4).compare(
        "ACC", "ACCATC").kind == MATCH_NONE


def test_subrepeat_does_nothing_without_an_edit_budget():
    """An exact tiling is already handled by period reduction, so the flag alone
    cannot change any verdict."""
    tolerance = MotifTolerance(min_subrepeat_motif=2)
    assert tolerance.compare("ACC", "ACCATC").kind == MATCH_NONE
    assert tolerance.compare("AC", "ACAC").kind == MATCH_EXACT   # period reduction


def test_tolerance_describe_names_each_rule_in_force():
    assert "1 edit" in MotifTolerance(max_edits=1).describe()
    assert "motif length" in MotifTolerance(max_edit_fraction=0.1).describe()
    assert "tiling" in MotifTolerance(max_edits=1, min_subrepeat_motif=3).describe()


def test_tolerance_never_beats_the_equivalence_policy():
    """Fuzziness must not smuggle in a strand match that --reverse-complement has
    not asked for. AAAGGG and CCCTTT are one repeat read from opposite strands and
    six edits apart, so only the policy can join them, never the budget."""
    generous = MotifTolerance(max_edits=3)
    assert generous.compare("AAAGGG", "CCCTTT").kind == MATCH_NONE
    assert generous.compare("AAAGGG", "CCCTTT", RC).kind == MATCH_EXACT


def test_max_fuzzy_motif_caps_every_loose_rule():
    long_query = "ACGT" * 20         # 80bp
    long_target = "ACGA" + "ACGT" * 19
    loose = MotifTolerance(max_edit_fraction=0.5, min_subrepeat_motif=4,
                           max_fuzzy_motif=200)
    assert loose.compare(long_query, long_target).matched
    capped = MotifTolerance(max_edit_fraction=0.5, min_subrepeat_motif=4,
                            max_fuzzy_motif=10)
    assert not capped.compare(long_query, long_target).matched


# --------------------------------------------------------------------------- #
# real motif pairs from pathogenic loci
#
# A step screening insertion sequences cannot know which strand a motif was
# called off, so it folds strands by default where a genome-wide screen does
# not. The strand-dependent cases below are therefore written against `RC`
# rather than the default equivalence.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("a,b,equivalence", [
    ("ATAT", "TA", DEFAULT_EQUIVALENCE),            # copies written out, rotation
    ("ccg", "CCG", DEFAULT_EQUIVALENCE),            # case
    (" CCG ", "CCG", DEFAULT_EQUIVALENCE),          # whitespace
    ("GGCGCGGAGC", "AGCGGCGCGG", DEFAULT_EQUIVALENCE),   # VWA1: rotations
    ("CCG", "CGG", RC),                             # opposite strands
])
def test_equivalent_motifs_share_a_key(a, b, equivalence):
    assert canonical_motif(a, equivalence) == canonical_motif(b, equivalence)


@pytest.mark.parametrize("a,b", [
    ("AAAAG", "AAGGG"),     # RFC1: reference vs pathogenic
    ("AAAAT", "TGAAA"),     # DAB1
    ("AAT", "AAC"),
    ("CCG", "CCGG"),
    ("A", "C"),
])
def test_distinct_motifs_have_distinct_keys(a, b):
    # Distinct under strand folding implies distinct without it, so assert both.
    for equivalence in (DEFAULT_EQUIVALENCE, RC):
        assert canonical_motif(a, equivalence) != canonical_motif(b, equivalence)


def test_every_rotation_and_strand_of_one_repeat_collapses():
    same = ["AAT", "ATA", "TAA", "ATT", "TTA", "TAT"]
    assert len({canonical_motif(m, RC) for m in same}) == 1


def test_canonical_motif_of_empty_is_empty():
    assert canonical_motif("") == ""
    assert canonical_motif("   ") == ""


@pytest.mark.parametrize("a,b,cutoff,expected", [
    ("ACGT", "ACGT", 2, 0),
    ("ACGT", "ACTT", 2, 1),
    ("ACGT", "ACT", 2, 1),
    ("ACGT", "AAAA", 1, 2),      # beyond cutoff -> cutoff + 1
    ("ACGT", "TTTTTTTT", 2, 3),  # length gap alone exceeds cutoff
])
def test_edit_distance(a, b, cutoff, expected):
    assert _edit_distance(a, b, cutoff) == expected


def test_motif_distance_scores_near_misses_only_when_asked():
    assert motif_distance("AAAAG", "AAAGG", 0) == 1
    assert motif_distance("AAAAG", "AAAGG", 1) == 1
    assert motif_distance("AAAAG", "AAGGG", 1) == 2


def test_motif_distance_handles_rotation_and_indels_together():
    assert motif_distance("GCCG", "CCG", 1) <= 1


def test_long_motifs_fall_back_to_exact_comparison():
    # Reduces to AC, so length is not an obstacle.
    assert motif_distance("AC" * 40, "CA", 2) == 0
    # Genuinely long irreducible motifs cannot be compared fuzzily. MAX_FUZZY_MOTIF
    # is 200, so this needs to be longer than the old 50 bp bound to be excluded.
    irreducible = "ACGT" * 60 + "A"     # 241 bp, no whole-number period
    assert motif_distance(irreducible, "ACGT", 2) == 3


def test_max_fuzzy_motif_is_tunable_per_call():
    long_a, long_b = "ACGTACGTACGTACGTACGTA", "ACGTACGTACGTACGTACGTC"   # 21 bp, 1 edit
    assert motif_distance(long_a, long_b, 1, max_fuzzy_motif=50) == 1
    assert motif_distance(long_a, long_b, 1, max_fuzzy_motif=10) == 2   # not attempted
