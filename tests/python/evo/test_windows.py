"""Window construction and the segment spans cut out of it."""

from __future__ import annotations

import pytest

from evo.embeddings import SEGMENTS, WindowSpec, build_window
from evo.utils import DictReference

# Four bases per block, so an offset that is wrong by one is visible in the
# output rather than hiding inside a run of identical bases.
CHR1 = "AAAACCCCGGGGTTTT"  # 0-based 0..15


@pytest.fixture
def ref():
    return DictReference({"chr1": CHR1, "chr2": "ACGT"})


def spans(window):
    """Segment name -> the actual subsequence it selects."""
    return {k: window.sequence[s.start : s.end] for k, s in window.segments.items()}


def test_insertion_lands_after_the_anchor_base(ref):
    # VCF POS 8 is the 8th base, 0-based index 7, the last base of the left
    # flank; the insertion follows it. Off by one here shifts every window.
    w = build_window(ref, "chr1", 8, "NNN", WindowSpec(flank=4, junction=2))
    assert w.sequence == "CCCC" + "NNN" + "GGGG"
    assert CHR1[7] == w.sequence[3], "left flank must end on the anchor base"


def test_segment_spans_select_what_they_name(ref):
    w = build_window(ref, "chr1", 8, "NNN", WindowSpec(flank=4, junction=2))
    got = spans(w)
    assert got["left"] == "CCCC"
    assert got["repeat"] == "NNN"
    assert got["right"] == "GGGG"
    # Junctions straddle their breakpoint: 2 bases either side.
    assert got["junction_5p"] == "CC" + "NN"
    assert got["junction_3p"] == "NN" + "GG"


def test_every_segment_is_always_present(ref):
    w = build_window(ref, "chr1", 8, "NNN", WindowSpec(flank=4, junction=2))
    assert set(w.segments) == set(SEGMENTS)


def test_reference_allele_has_empty_repeat_and_coincident_junctions(ref):
    """`insert=""` is how background windows are built -- same construction, no
    insertion, so the only difference from an ALT window is the insertion."""
    w = build_window(ref, "chr1", 8, "", WindowSpec(flank=4, junction=2))
    assert w.sequence == "CCCCGGGG"
    got = spans(w)
    assert got["repeat"] == ""
    assert got["junction_5p"] == got["junction_3p"] == "CCGG"
    assert w.insert_length == 0


def test_flank_is_clipped_not_padded_at_contig_start(ref):
    """A short flank must stay short. Padding would embed invented bases."""
    w = build_window(ref, "chr1", 2, "N", WindowSpec(flank=8, junction=2))
    assert w.sequence == "AA" + "N" + "AACCCCGG"
    assert spans(w)["left"] == "AA"
    assert not w.segments["left"].complete


def test_flank_is_clipped_at_contig_end(ref):
    w = build_window(ref, "chr1", 14, "N", WindowSpec(flank=8, junction=2))
    assert spans(w)["right"] == "TT"
    assert not w.segments["right"].complete


@pytest.mark.parametrize(
    "insert,crop,expected",
    [
        ("ABCDEFGHIJ", 4, "DEFG"),   # centred: offset (10-4)//2 = 3
        ("ABCD", 4, "ABCD"),         # exactly at the cap, untouched
        ("ABC", 4, "ABC"),           # under the cap, untouched
        ("ABCDEFGHIJ", None, "ABCDEFGHIJ"),  # cap off
    ],
)
def test_long_insertions_are_centre_cropped(ref, insert, crop, expected):
    w = build_window(ref, "chr1", 8, insert, WindowSpec(flank=4, repeat_crop=crop))
    assert spans(w)["repeat"] == expected


def test_crop_records_original_length_as_a_covariate(ref):
    """Clusters can be driven by insertion length alone; the pre-crop length has
    to survive cropping or that cannot be checked."""
    w = build_window(ref, "chr1", 8, "N" * 5000, WindowSpec(flank=4, repeat_crop=100))
    assert w.insert_length == 5000
    assert w.cropped
    assert len(spans(w)["repeat"]) == 100


def test_uncropped_window_is_not_flagged(ref):
    w = build_window(ref, "chr1", 8, "NNN", WindowSpec(flank=4, repeat_crop=100))
    assert not w.cropped
    assert w.segments["repeat"].complete


def test_rep_span_selects_one_trf_call_within_the_insertion(ref):
    """Without rep_start/rep_end every TRF call from one insertion would pool an
    identical `repeat` vector."""
    w = build_window(
        ref, "chr1", 8, "ABCDEFGH", WindowSpec(flank=4, repeat_crop=None),
        rep_start=2, rep_end=5,
    )
    assert spans(w)["repeat"] == "CDE"


def test_rep_span_is_shifted_by_the_crop(ref):
    # crop 4 of 10 -> offset 3, so insertion offsets 3..7 become window-relative
    # 0..4 within the kept text.
    w = build_window(
        ref, "chr1", 8, "ABCDEFGHIJ", WindowSpec(flank=4, repeat_crop=4),
        rep_start=3, rep_end=6,
    )
    assert spans(w)["repeat"] == "DEF"


def test_rep_span_outside_the_crop_collapses_rather_than_escaping(ref):
    """A TRF call cropped away must not leak into the flanks."""
    w = build_window(
        ref, "chr1", 8, "ABCDEFGHIJ", WindowSpec(flank=4, repeat_crop=2),
        rep_start=0, rep_end=2,
    )
    rep = w.segments["repeat"]
    assert len(rep) == 0
    assert not rep.complete


def test_window_length_is_bounded_by_the_spec(ref):
    spec = WindowSpec(flank=4, repeat_crop=6)
    w = build_window(ref, "chr1", 8, "N" * 1000, spec)
    assert len(w.sequence) <= spec.max_length


def test_soft_masked_reference_is_upper_cased():
    """hg38 is soft-masked and Evo 2 tokenizes bytes, so `a` and `A` differ."""
    w = build_window(
        DictReference({"chr1": "aaaacccc"}), "chr1", 4, "gg", WindowSpec(flank=4)
    )
    assert w.sequence == "AAAAggCCCC"


def test_unknown_contig_is_an_error(ref):
    with pytest.raises(KeyError, match="chr99"):
        build_window(ref, "chr99", 8, "N")


def test_negative_coordinate_is_an_error(ref):
    with pytest.raises(ValueError, match="non-negative"):
        build_window(ref, "chr1", -1, "N")
