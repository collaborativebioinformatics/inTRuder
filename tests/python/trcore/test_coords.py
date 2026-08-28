"""Coordinate conventions -- the shared definition of 'where' and 'how far'.

Both steps convert VCF coordinates and measure distance to an interval. When
those two disagree by a base, the tables they produce look comparable and are
not, so the rules live in one place and are tested once.
"""

from __future__ import annotations

import pytest

from intruder.trcore.coords import interval_distance, normalize_chrom, to_external, to_internal


@pytest.mark.parametrize("raw,expected", [
    ("chr1", "chr1"), ("1", "chr1"), (" 1 ", "chr1"), ("X", "chrX"),
    ("chrX", "chrX"), ("MT", "chrM"), ("chrMT", "chrM"), ("M", "chrM"),
    (1, "chr1"),
])
def test_normalize_chrom(raw, expected):
    assert normalize_chrom(raw) == expected


def test_to_internal_shifts_only_one_based_input():
    assert to_internal(10001, coord_base=1) == 10000
    assert to_internal(10000, coord_base=0) == 10000


def test_to_external_is_the_inverse():
    assert to_external(10000, 10468, coord_base=1) == (10001, 10468)
    assert to_external(10000, 10468, coord_base=0) == (10000, 10468)
    start = to_internal(10001, coord_base=1)
    assert to_external(start, start + 1, coord_base=1)[0] == 10001


# The interval under test is [100, 200): first base 100, last base 199.
@pytest.mark.parametrize("start,end,expected", [
    (100, 101, 0),      # first base
    (199, 200, 0),      # last base
    (100, 200, 0),      # exactly the interval
    (50, 150, 0),       # straddles the left edge
    (150, 250, 0),      # straddles the right edge
    (0, 1000, 0),       # contains it
    (99, 100, 1),       # one base to the left
    (200, 201, 1),      # one base to the right (end is exclusive)
    (0, 100, 1),        # abuts the left edge
    (90, 91, 10),
    (209, 210, 10),
])
def test_interval_distance_is_symmetric_and_zero_on_overlap(start, end, expected):
    assert interval_distance(start, end, 100, 200) == expected


def test_interval_distance_is_commutative():
    for a, b in [((0, 10), (100, 200)), ((150, 160), (100, 200)), ((300, 400), (100, 200))]:
        assert interval_distance(*a, *b) == interval_distance(*b, *a)
