"""Command-line plumbing: shard selection, layer and pooling resolution."""

from __future__ import annotations

import pytest

from evo.embeddings.cli import build_parser, resolve_layers, resolve_pooling, select
from evo.embeddings.extract import (
    LAYER_SETS,
    OVERFLOWS_FLOAT16,
    SEGMENT_POOLING,
)

HEADER = """\
##fileformat=VCFv4.1
##INFO=<ID=SVTYPE,Number=1,Type=String,Description="Type">
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\tS2\tS3
"""
FMT = "GT:LN:ID:RAL:AAL:CO"
UNCALLED = "./.:0:NaN:NAN:NAN:NAN"


def record(pos, info, *cells):
    return (f"chr1\t{pos}\tREC\tG\tGAAA\t.\tPASS\t{info}\t{FMT}\t"
            + "\t".join(cells) + "\n")


def called(ln, svid, ral, aal, co):
    return f"0/1:{ln}:{svid}:{ral}:{aal}:{co}"


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
    assert resolve_layers("deep") == list(LAYER_SETS["deep"])


def test_the_default_layer_set_survives_float16():
    """The 2026-08-27 run spent its GPU hours writing +/-inf for two layers.

    Nothing at extraction time can tell you that: the cast is silent and the
    file loads. So the guard is here, on the set that runs when nobody passes
    `--layers` -- the one case where the mistake is made by omission.
    """
    args = build_parser().parse_args(["a.vcf", "ref.fa", "out.npz"])
    layers = resolve_layers(args.layers)
    assert set(layers).isdisjoint(OVERFLOWS_FLOAT16), args.layers



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


# --- build_windows ------------------------------------------------------------

def insertion(chrom, pos, sample, svid, insert):
    from evo.embeddings.loci import InsertionCall

    return InsertionCall(chrom=chrom, pos=pos, record_pos=pos, sample=sample,
                         svid=svid, insert=insert, declared_length=len(insert))


@pytest.fixture
def reference():
    from evo.utils import DictReference

    return DictReference({"chr1": "ACGT" * 16})


@pytest.fixture
def three_samples():
    """Two breakpoints; the first called in two samples with different alleles."""
    return [
        insertion("chr1", 20, "S1", "v1", "AAAA"),
        insertion("chr1", 20, "S2", "v2", "AAAAAA"),
        insertion("chr1", 40, "S1", "v3", "CCCC"),
    ]


def test_alt_mode_keeps_one_window_per_call(reference, three_samples):
    from evo.embeddings.cli import build_windows
    from evo.embeddings.windows import WindowSpec

    windows, samples, svids, skipped = build_windows(
        three_samples, reference, WindowSpec(flank=8, junction=2)
    )
    assert len(windows) == 3
    assert samples == ["S1", "S2", "S1"]
    assert svids == ["v1", "v2", "v3"]
    assert skipped == 0
    assert [w.insert_length for w in windows] == [4, 6, 4]


def test_background_mode_deduplicates_breakpoints(reference, three_samples):
    """One reference allele per breakpoint, not per call: it does not depend on
    who was called there, and embedding it 69 times would cost 69x."""
    from evo.embeddings.cli import build_windows
    from evo.embeddings.windows import WindowSpec

    windows, samples, svids, _ = build_windows(
        three_samples, reference, WindowSpec(flank=8, junction=2), background=True
    )
    assert [(w.chrom, w.ins_coord) for w in windows] == [("chr1", 20), ("chr1", 40)]
    assert samples == ["", ""]
    assert svids == ["", ""]


def test_background_windows_carry_no_insertion(reference, three_samples):
    from evo.embeddings.cli import build_windows
    from evo.embeddings.windows import WindowSpec

    windows, _, _, _ = build_windows(
        three_samples, reference, WindowSpec(flank=8, junction=2), background=True
    )
    for window in windows:
        assert window.insert_length == 0
        assert not window.cropped
        assert len(window.segments["repeat"]) == 0


def test_background_flanks_match_the_alt_window_exactly(reference, three_samples):
    """What makes `alt - reference` a controlled comparison: the two windows are
    built the same way from the same breakpoint, differing only by the insert."""
    from evo.embeddings.cli import build_windows
    from evo.embeddings.windows import WindowSpec

    spec = WindowSpec(flank=8, junction=2)
    alt, _, _, _ = build_windows(three_samples[:1], reference, spec)
    ref, _, _, _ = build_windows(three_samples[:1], reference, spec, background=True)
    left = alt[0].segments["left"]
    assert alt[0].sequence[left.start : left.end] == ref[0].sequence[
        ref[0].segments["left"].start : ref[0].segments["left"].end
    ]


def test_contigs_absent_from_the_reference_are_counted_not_embedded(reference):
    from evo.embeddings.cli import build_windows
    from evo.embeddings.windows import WindowSpec

    calls = [insertion("chrZ", 20, "S1", "v1", "AAAA"),
             insertion("chr1", 20, "S1", "v2", "AAAA")]
    windows, _, _, skipped = build_windows(calls, reference, WindowSpec(flank=8))
    assert len(windows) == 1 and skipped == 1


# --- run_shard ----------------------------------------------------------------
# The one code path both entry points use. Everything here is about the seam
# between window building and storage, which is where a label can silently slip.

@pytest.fixture
def gappy_reference():
    """chr1 has a 40-base N block at the front, like a telomere."""
    from evo.utils import DictReference

    return DictReference({"chr1": "N" * 40 + "ACGT" * 24})


def test_dry_run_reports_survivors_without_loading_a_model(tmp_path, gappy_reference):
    """The count must be post-N-filter: it is the number quoted when sizing GPU
    time, and the whole point of --dry-run is to get it on a laptop."""
    from evo.embeddings.cli import run_shard
    from evo.embeddings.windows import WindowSpec

    vcf = tmp_path / "t.vcf"
    vcf.write_text(HEADER + record(8, "SVTYPE=INS", called(4, "v1", "G", "GAAAA",
                                                           "chr1_8-chr1_8"), UNCALLED,
                                   UNCALLED)
                   + record(80, "SVTYPE=INS", called(4, "v2", "G", "GAAAA",
                                                     "chr1_80-chr1_80"), UNCALLED,
                            UNCALLED))
    out = tmp_path / "out.npz"
    n = run_shard(str(out), str(vcf), gappy_reference, WindowSpec(flank=8, junction=2),
                  layers=["blocks.1"], segments=["repeat"], pooling={"repeat": "mean"})
    assert n == 1              # the window at pos 8 is inside the N block
    assert not out.exists()


def test_labels_stay_attached_when_the_n_filter_drops_a_window(tmp_path, gappy_reference):
    """extract() returns only surviving windows, so sample/svid have to be
    re-derived from them -- not zipped against the original list."""
    from evo.embeddings.cli import run_shard
    from evo.embeddings.extract import KmerEmbedder
    from evo.embeddings.store import load
    from evo.embeddings.windows import WindowSpec

    vcf = tmp_path / "t.vcf"
    vcf.write_text(
        HEADER
        + record(8, "SVTYPE=INS", called(4, "dropped", "G", "GAAAA", "chr1_8-chr1_8"),
                 UNCALLED, UNCALLED)
        + record(80, "SVTYPE=INS", called(4, "kept", "G", "GCCCC", "chr1_80-chr1_80"),
                 UNCALLED, UNCALLED)
    )
    out = tmp_path / "out.npz"
    rows = run_shard(str(out), str(vcf), gappy_reference, WindowSpec(flank=8, junction=2),
                     layers=["blocks.1"], segments=["repeat"], pooling={"repeat": "mean"},
                     embedder=KmerEmbedder(k=2), model="kmer")
    assert rows == 1
    stored = load(str(out))
    assert list(stored.meta["svid"]) == ["kept"]
    assert list(stored.meta["pos"]) == [80]


def test_background_and_alt_differ_only_in_the_allele_they_record(tmp_path,
                                                                  gappy_reference):
    from evo.embeddings.cli import run_shard
    from evo.embeddings.extract import KmerEmbedder
    from evo.embeddings.store import load
    from evo.embeddings.windows import WindowSpec

    vcf = tmp_path / "t.vcf"
    vcf.write_text(HEADER + record(80, "SVTYPE=INS",
                                   called(4, "v1", "G", "GAAAA", "chr1_80-chr1_80"),
                                   UNCALLED, UNCALLED))
    spec = WindowSpec(flank=8, junction=2)
    common = {"layers": ["blocks.1"], "segments": ["repeat"],
              "pooling": {"repeat": "mean"}, "embedder": KmerEmbedder(k=2),
              "model": "kmer"}
    run_shard(str(tmp_path / "a.npz"), str(vcf), gappy_reference, spec, **common)
    run_shard(str(tmp_path / "r.npz"), str(vcf), gappy_reference, spec,
              background=True, **common)
    alt, ref = load(str(tmp_path / "a.npz")), load(str(tmp_path / "r.npz"))
    assert (alt.attrs["allele"], ref.attrs["allele"]) == ("alt", "reference")
    assert alt.attrs["flank"] == ref.attrs["flank"]
    assert list(alt.meta["insert_length"]) == [4]
    assert list(ref.meta["insert_length"]) == [0]
