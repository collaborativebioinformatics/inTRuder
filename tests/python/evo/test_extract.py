"""Pooling, strand handling and the extraction loop."""

from __future__ import annotations

import numpy as np
import pytest

from evo.embeddings.extract import (
    BLOCK_TYPES,
    LAYER_SETS,
    N_BLOCKS,
    extract,
    extract_window,
    pool,
    reverse_complement,
    reverse_span,
)
from evo.embeddings.windows import WindowSpec, build_window
from evo.utils import DictReference

WIDTH = 4


class PositionEmbedder:
    """Per-token vectors that encode the token's own index.

    Token *i* becomes ``[i, i, i, i]``, so a pooled vector states exactly which
    positions went into it. That turns "did we pool the right span, on the right
    strand" into an arithmetic assertion rather than a shape check.
    """

    width = WIDTH

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, sequence, layers):
        self.calls.append(sequence)
        idx = np.arange(len(sequence), dtype=np.float32)[:, None]
        return {name: np.repeat(idx, WIDTH, axis=1) for name in layers}


@pytest.fixture
def ref():
    return DictReference({"chr1": "ACGT" * 64})


@pytest.fixture
def window(ref):
    return build_window(ref, "chr1", 128, "TTTT",
                        WindowSpec(flank=16, junction=4, repeat_crop=None))


# --- primitives ---------------------------------------------------------------

def test_reverse_complement():
    assert reverse_complement("ACGTN") == "NACGT"


def test_reverse_complement_is_an_involution():
    seq = "ACGTTTGCANRY"
    assert reverse_complement(reverse_complement(seq)) == seq


def test_reverse_complement_handles_iupac_and_case():
    assert reverse_complement("acgtRY") == "RYacgt"


@pytest.mark.parametrize("start,end,length,expected", [
    (0, 10, 100, (90, 100)),   # front of the forward strand -> back of reverse
    (90, 100, 100, (0, 10)),
    (40, 60, 100, (40, 60)),   # a centred span stays centred
])
def test_reverse_span(start, end, length, expected):
    assert reverse_span(start, end, length) == expected


def test_reverse_span_round_trips():
    a, b = reverse_span(*reverse_span(7, 19, 50), 50)
    assert (a, b) == (7, 19)


# --- pooling ------------------------------------------------------------------

def test_mean_pooling_averages_the_span():
    tokens = np.arange(10, dtype=np.float32)[:, None]
    assert pool(tokens, 2, 6, "mean")[0] == pytest.approx(3.5)


def test_last_pooling_takes_the_final_token():
    tokens = np.arange(10, dtype=np.float32)[:, None]
    assert pool(tokens, 2, 6, "last")[0] == 5.0


def test_empty_span_pools_to_zeros_rather_than_raising():
    """A reference-allele window has no repeat; it must still yield a full
    fixed-shape block so rows stay aligned with metadata."""
    tokens = np.arange(10, dtype=np.float32)[:, None]
    assert pool(tokens, 4, 4, "mean").tolist() == [0.0]


def test_unknown_pooling_is_rejected():
    with pytest.raises(ValueError, match="unknown pooling"):
        pool(np.zeros((4, 1)), 0, 2, "median")


# --- per-window extraction ----------------------------------------------------

def test_shape_is_layers_by_segments_by_double_width(window):
    v = extract_window(window, PositionEmbedder(), ["a", "b"])
    assert v.shape == (2, 5, 2 * WIDTH)


def test_both_strands_are_run_once_each(window):
    e = PositionEmbedder()
    extract_window(window, e, ["a", "b"])
    assert len(e.calls) == 2, "one pass per strand, not one per layer"
    assert e.calls[1] == reverse_complement(e.calls[0])


def test_forward_half_pools_the_forward_span(window):
    v = extract_window(window, PositionEmbedder(), ["a"], segments=["repeat"],
                       pooling={"repeat": "mean"})
    span = window.segments["repeat"]
    expected = np.arange(span.start, span.end).mean()
    assert v[0, 0, :WIDTH] == pytest.approx(expected)


def test_reverse_half_pools_the_mirrored_span(window):
    v = extract_window(window, PositionEmbedder(), ["a"], segments=["repeat"],
                       pooling={"repeat": "mean"})
    span = window.segments["repeat"]
    lo, hi = reverse_span(span.start, span.end, len(window.sequence))
    assert v[0, 0, WIDTH:] == pytest.approx(np.arange(lo, hi).mean())


def test_last_pooling_reads_opposite_ends_on_the_two_strands(window):
    """The point of the strand pair: forward-last sees the span's 3' end with
    everything upstream behind it, reverse-last sees its 5' end."""
    v = extract_window(window, PositionEmbedder(), ["a"], segments=["junction_5p"],
                       pooling={"junction_5p": "last"})
    span = window.segments["junction_5p"]
    length = len(window.sequence)
    assert v[0, 0, 0] == span.end - 1
    assert v[0, 0, WIDTH] == reverse_span(span.start, span.end, length)[1] - 1


# --- the extraction loop ------------------------------------------------------

def test_extract_stacks_windows(ref):
    windows = [build_window(ref, "chr1", p, "TT", WindowSpec(flank=8, junction=2))
               for p in (32, 64, 96)]
    v, kept = extract(windows, PositionEmbedder(), layers=["a"])
    assert v.shape == (3, 1, 5, 2 * WIDTH)
    assert len(kept) == 3


def test_n_heavy_windows_are_skipped_and_kept_list_stays_aligned():
    """Dropping rows without dropping the matching metadata is exactly how a
    silent off-by-N gets into a cluster plot."""
    ref = DictReference({"chr1": "N" * 64 + "ACGT" * 32})
    gappy = build_window(ref, "chr1", 16, "TT", WindowSpec(flank=16, junction=2))
    clean = build_window(ref, "chr1", 150, "TT", WindowSpec(flank=16, junction=2))
    assert gappy.n_fraction > 0.1 and clean.n_fraction == 0.0

    v, kept = extract([gappy, clean], PositionEmbedder(), layers=["a"],
                      max_n_fraction=0.1)
    assert len(v) == 1
    assert kept == [clean]


def test_n_filter_can_be_disabled():
    ref = DictReference({"chr1": "N" * 64 + "ACGT" * 32})
    gappy = build_window(ref, "chr1", 16, "TT", WindowSpec(flank=16, junction=2))
    v, kept = extract([gappy], PositionEmbedder(), layers=["a"], max_n_fraction=None)
    assert len(v) == 1 and kept == [gappy]


def test_extract_with_everything_filtered_returns_a_correctly_shaped_empty():
    ref = DictReference({"chr1": "N" * 128})
    gappy = build_window(ref, "chr1", 32, "TT", WindowSpec(flank=16, junction=2))
    v, kept = extract([gappy], PositionEmbedder(), layers=["a", "b"],
                      max_n_fraction=0.1)
    assert v.shape == (0, 2, 5, 2 * WIDTH) and kept == []


# --- layer catalogue ----------------------------------------------------------

def test_block_types_partition_every_block():
    seen = sorted(i for group in BLOCK_TYPES.values() for i in group)
    assert seen == list(range(N_BLOCKS)), "each block has exactly one type"


def test_attention_blocks_match_the_checkpoint():
    assert BLOCK_TYPES["attention"] == (3, 10, 17, 24, 31)


@pytest.mark.parametrize("name", list(LAYER_SETS))
def test_named_layer_sets_are_non_empty_and_unique(name):
    layers = LAYER_SETS[name]
    assert layers and len(set(layers)) == len(layers)


# --- the k-mer stand-in -------------------------------------------------------

def test_kmer_mean_pooling_is_a_kmer_frequency_vector():
    """The property that makes it a usable stand-in rather than noise."""
    from evo.embeddings.extract import KmerEmbedder

    e = KmerEmbedder(k=2)
    seq = "ACACACAC"
    tokens = e(seq, ["a"])["a"]
    v = pool(tokens, 0, len(seq), "mean")
    assert v.sum() == pytest.approx(7 / 8)          # first base has no full 2-mer
    top = np.argsort(v)[-2:]
    ac = 0 * 4 + 1  # AC
    ca = 1 * 4 + 0  # CA
    assert set(top.tolist()) == {ac, ca}


def test_kmer_width_is_four_to_the_k():
    from evo.embeddings.extract import KmerEmbedder

    assert KmerEmbedder(k=4).width == 256


def test_kmer_resets_across_n_runs():
    """An N must not silently produce a k-mer spanning the gap."""
    from evo.embeddings.extract import KmerEmbedder

    e = KmerEmbedder(k=3)
    tokens = e("ACNGT", ["a"])["a"]
    assert tokens.sum() == 0.0


def test_kmer_satisfies_the_embedder_protocol(ref):
    from evo.embeddings.extract import KmerEmbedder

    w = build_window(ref, "chr1", 128, "TTTT", WindowSpec(flank=16, junction=4))
    v = extract_window(w, KmerEmbedder(k=3), ["a"])
    assert v.shape == (1, 5, 2 * 64)
