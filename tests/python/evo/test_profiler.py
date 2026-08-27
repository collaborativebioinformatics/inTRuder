"""The profiler's baseline must be the production path, or its verdict is noise.

The variants are compared on the worker against whichever runs first, so the
whole chain of equivalence rests on that first one -- ``variant_host`` --
actually reproducing :func:`evo.embeddings.extract.extract_window`. The GPU
halves cannot be checked here (no CUDA, no ``evo2``, and this project's default
interpreter cannot even install torch), but the span mapping and the host
pooling are pure array work and are exactly where a strand or an off-by-one
mistake would hide.
"""

from __future__ import annotations

import numpy as np
import pytest

from evo.embeddings.extract import SEGMENT_POOLING, extract_window
from evo.embeddings.windows import SEGMENTS, WindowSpec, build_window
from evo.profiler.throughput import (
    PROFILED_LAYERS,
    VARIANTS,
    pooled_on_host,
    spans_for,
)
from evo.utils import DictReference

WIDTH = 4
LAYERS = ("blocks.16", "blocks.26")


class PositionEmbedder:
    """Token *i* becomes ``[i, i, i, i]`` -- a pooled vector states its own span."""

    width = WIDTH

    def __call__(self, sequence, layers):
        idx = np.arange(len(sequence), dtype=np.float32)[:, None]
        return {name: np.repeat(idx, WIDTH, axis=1) for name in layers}


@pytest.fixture
def window():
    ref = DictReference({"chr1": "ACGT" * 64})
    return build_window(ref, "chr1", 128, "TTTT",
                        WindowSpec(flank=32, junction=8))


def test_host_pooling_reproduces_extract_window(window):
    """Same numbers as production, laid out the same way.

    ``extract_window`` returns ``(layers, segments, 2 * width)`` with the
    forward and reverse halves concatenated on the last axis; the profiler
    builds each half separately and concatenates. If those two ever disagree,
    every speedup the profiler reports is measured against the wrong thing.
    """
    embedder = PositionEmbedder()
    expected = extract_window(window, embedder, LAYERS, SEGMENTS, SEGMENT_POOLING)

    tokens = {
        layer: embedder(window.sequence, LAYERS)[layer] for layer in LAYERS
    }
    from evo.embeddings.extract import reverse_complement

    rc_tokens = {
        layer: embedder(reverse_complement(window.sequence), LAYERS)[layer]
        for layer in LAYERS
    }
    got = np.concatenate(
        [
            pooled_on_host(tokens, spans_for(window, reverse=False)),
            pooled_on_host(rc_tokens, spans_for(window, reverse=True)),
        ],
        axis=-1,
    )
    np.testing.assert_allclose(got, expected)


def test_spans_are_mirrored_on_the_reverse_strand(window):
    """A span's reverse coordinates are the forward ones reflected in the window."""
    length = len(window.sequence)
    for (fs, fe, fh), (rs, re, rh) in zip(
        spans_for(window, reverse=False), spans_for(window, reverse=True)
    ):
        assert (rs, re) == (length - fe, length - fs)
        assert fh == rh  # strand must not change how a segment is pooled


def test_spans_cover_every_segment_in_order(window):
    assert len(spans_for(window, reverse=False)) == len(SEGMENTS)
    assert [how for _, _, how in spans_for(window, reverse=False)] == [
        SEGMENT_POOLING[name] for name in SEGMENTS
    ]


def test_the_profiler_measures_the_set_that_actually_runs():
    """A profile of layers nobody extracts is a number about nothing."""
    from evo.embeddings.cli import build_parser, resolve_layers

    args = build_parser().parse_args(["a.vcf", "ref.fa", "out.npz"])
    assert list(PROFILED_LAYERS) == resolve_layers(args.layers)


def test_host_is_the_declared_baseline():
    """`profile_variant` compares against the first variant run, so order matters."""
    assert next(iter(VARIANTS)) == "host"
