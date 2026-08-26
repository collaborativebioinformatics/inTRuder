"""Motif canonicalisation -- run with `uv run pytest`."""

from __future__ import annotations

from itertools import product

import pytest

from novelty.motifs import (
    canonical_motif,
    canonical_motifs,
    least_rotation,
    motif_distance,
    primitive_unit,
    reverse_complement,
)


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


def test_canonical_motif_collapses_rotation_and_strand():
    # GC and CG are the same 2bp repeat.
    assert canonical_motif("GC") == canonical_motif("CG")
    # All rotations and both strands of the AAT repeat collapse together.
    same = ["AAT", "ATA", "TAA", "ATT", "TTA", "TAT"]
    assert len({canonical_motif(m) for m in same}) == 1
    # A period-4 consensus that is really a 2-mer reduces to the 2-mer.
    assert canonical_motif("ATAT") == canonical_motif("TA") == "AT"
    # Genuinely different motifs stay apart.
    assert canonical_motif("AAT") != canonical_motif("AAC")


def test_canonical_motif_stranded_keeps_reverse_complement_distinct():
    assert canonical_motif("AAT", stranded=True) != canonical_motif("ATT", stranded=True)
    assert canonical_motif("AAT", stranded=True) == canonical_motif("ATA", stranded=True)


@pytest.mark.parametrize("stranded", [False, True])
def test_canonical_motifs_matches_the_scalar_version(stranded):
    """The vectorised path canonicalises the uniques and broadcasts them back."""
    values = ["GC", "cg", " AT ", "ATAT", "AAT", "GC", "", None]
    got = canonical_motifs(values, stranded=stranded)
    want = [canonical_motif(v or "", stranded=stranded) for v in values]
    assert list(got) == want


def test_canonical_motifs_handles_an_empty_input():
    assert list(canonical_motifs([])) == []


@pytest.mark.parametrize("a,b,expected", [
    ("AAT", "ATA", 0),      # rotation
    ("AAT", "ATT", 0),      # reverse complement
    ("AAT", "AAC", 1),      # one substitution
    ("AATG", "AAG", 1),     # one deletion
    ("AAT", "GGC", 3),      # canonical AAT vs CCG -- three substitutions
])
def test_motif_distance(a, b, expected):
    assert motif_distance(a, b, cutoff=3) == expected


def test_motif_distance_beyond_cutoff_is_capped():
    """Past the cutoff the exact distance is not computed, only `cutoff + 1`."""
    assert motif_distance("AAT", "GGC", cutoff=2) == 3
    assert motif_distance("AAT", "GGC", cutoff=1) == 2


def test_motif_distance_respects_cutoff():
    assert motif_distance("AAT", "AAC", cutoff=0) == 1   # cutoff + 1
    assert motif_distance("AAT", "AAC", cutoff=1) == 1
