"""Taking AnnotSV's multi-value fields apart without corrupting them.

AnnotSV packs several values into one field, and it does it three different ways
in the same row. Getting the three confused does not crash anything — it
mislabels a gene, quietly, on a page whose whole job is to say which gene an
insertion is in. That is why this is a test file and not a comment.

The three shapes, and the one function each needs, are argued in
`scripts/build_web_tables.py`. What is pinned here is the behaviour of
`annotsv_collapse`, which is the only one with a non-obvious contract: it has to
undo AnnotSV's per-transcript repetition WITHOUT touching a value whose commas
are its own. Those two cases look identical to a naive split, and the real data
contains both — 1,996 HPRC loci carry a repeated phenotype, and 26,962 rows carry
a phenotype with a comma inside it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_web_tables import annotsv_collapse  # noqa: E402


class TestRepetitionIsUndone:
    """A value repeated once per overlapping transcript collapses to one copy."""

    def test_doubled(self):
        assert annotsv_collapse("NR_188197, NR_188197") == "NR_188197"

    def test_tripled_with_internal_commas(self):
        """The DIP2B case: three copies of a value that itself holds commas.

        This is the one that makes the period search necessary rather than a
        `set()` — de-duplicating the chunks would return the four distinct chunks
        of one copy in arbitrary order, not the copy.
        """
        one = "Intellectual developmental disorder, AD, FRA12A type, 136630 (3) AD"
        assert annotsv_collapse(", ".join([one] * 3)) == one

    def test_doubled_with_internal_commas(self):
        one = "Spermatogenic failure 92, 620848 (3) AR"
        assert annotsv_collapse(f"{one}, {one}") == one


class TestOwnCommasSurvive:
    """A value whose commas are part of its text is returned untouched.

    If any of these ever collapse, the page starts captioning genes with a
    fragment of their own phenotype — `AR` instead of `Myopia 23, AR, 615431 (3)
    AR`, which is exactly the bug this function exists to prevent.
    """

    @pytest.mark.parametrize(
        "value",
        [
            "Myopia 23, AR, 615431 (3) AR",
            "Marbach-Schaaf neurodevelopmental syndrome, 619680 (3) AD",
            "Deafness, AR 23, 609533 (3) AR;Usher syndrome, type 1F, 602083 (3) AR",
            "CDS, UTR",
            "single value",
        ],
    )
    def test_unchanged(self, value):
        assert annotsv_collapse(value) == value

    def test_a_near_repeat_is_not_a_repeat(self):
        """Two similar-but-different values must both survive.

        The period has to match at every position, not merely divide the length,
        or two genes with almost the same phenotype would collapse into one.
        """
        value = "Deafness, AR 23, 609533 (3) AR, Deafness, AR 24, 609533 (3) AR"
        assert annotsv_collapse(value) == value


class TestEdges:
    def test_none_passes_through(self):
        assert annotsv_collapse(None) is None

    def test_empty_string(self):
        assert annotsv_collapse("") == ""

    def test_odd_count_is_not_collapsed_to_a_half(self):
        """Three chunks of two distinct values is not a repetition of either.

        A period must divide the chunk count exactly; `A, B, A` has none, and
        returning `A, B` would invent a value the row never carried.
        """
        assert annotsv_collapse("A, B, A") == "A, B, A"

    def test_a_genuinely_repeated_pair(self):
        assert annotsv_collapse("A, B, A, B") == "A, B"
