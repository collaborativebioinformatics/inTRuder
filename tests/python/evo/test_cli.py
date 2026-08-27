"""Command-line plumbing: shard selection, layer and pooling resolution."""

from __future__ import annotations

import pytest

from evo.embeddings.cli import build_parser, resolve_layers, resolve_pooling, select
from evo.embeddings.extract import LAYER_SETS, SEGMENT_POOLING


def calls(n):
    """Stand-ins for InsertionCall -- select() only ever indexes, never reads."""
    return [f"c{i}" for i in range(n)]


# --- select -------------------------------------------------------------------

def test_offset_skips_and_limit_stops():
    assert list(select(calls(10), offset=3, limit=4)) == ["c3", "c4", "c5", "c6"]


def test_offset_alone_runs_to_the_end():
    assert list(select(calls(5), offset=2)) == ["c2", "c3", "c4"]


def test_limit_alone_is_a_prefix():
    """The pre-existing meaning of --limit, unchanged by --offset."""
    assert list(select(calls(5), limit=2)) == ["c0", "c1"]


def test_defaults_pass_everything_through():
    assert list(select(calls(4))) == calls(4)


def test_shards_partition_the_input_exactly():
    """The property the whole flag exists for: no gaps, no overlaps, no losses."""
    source = calls(6083)
    shards = [list(select(source, offset=o, limit=2000)) for o in (0, 2000, 4000, 6000)]
    assert [len(s) for s in shards] == [2000, 2000, 2000, 83]
    assert [c for shard in shards for c in shard] == source


def test_a_shard_past_the_end_is_empty_not_an_error():
    assert list(select(calls(10), offset=99, limit=5)) == []


def test_limit_zero_selects_nothing():
    assert list(select(calls(10), offset=2, limit=0)) == []


def test_input_is_consumed_lazily():
    """A shard must not pull the whole VCF into memory to reach its slice."""
    seen = []

    def source():
        for i in range(1000):
            seen.append(i)
            yield f"c{i}"

    assert list(select(source(), offset=2, limit=2)) == ["c2", "c3"]
    assert max(seen) == 4, "read past the end of the shard"


@pytest.mark.parametrize("offset,limit", [(-1, None), (0, -5)])
def test_negative_bounds_are_rejected(offset, limit):
    with pytest.raises(SystemExit):
        list(select(calls(3), offset=offset, limit=limit))


# --- parser -------------------------------------------------------------------

def test_offset_defaults_to_zero_and_limit_to_none():
    args = build_parser().parse_args(["a.vcf", "ref.fa", "out.npz"])
    assert (args.offset, args.limit) == (0, None)


# --- resolve_layers / resolve_pooling ----------------------------------------

def test_named_layer_set_expands():
    assert resolve_layers("default") == list(LAYER_SETS["default"])


def test_comma_separated_layers_are_taken_literally():
    assert resolve_layers("blocks.1, blocks.2") == ["blocks.1", "blocks.2"]


def test_empty_layer_spec_is_rejected():
    with pytest.raises(SystemExit):
        resolve_layers(" , ")


def test_pooling_override_touches_only_the_named_segment():
    pooling = resolve_pooling("repeat=last")
    assert pooling["repeat"] == "last"
    assert {k: v for k, v in pooling.items() if k != "repeat"} == \
        {k: v for k, v in SEGMENT_POOLING.items() if k != "repeat"}


@pytest.mark.parametrize("spec", ["repeat=median", "nosuch=mean"])
def test_bad_pooling_is_rejected(spec):
    with pytest.raises(SystemExit):
        resolve_pooling(spec)
