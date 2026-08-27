"""``python -m evo.embeddings``: both alleles, one model load, one directory.

The property under test is the one the first full run got wrong -- a job that
was asked for the reference genome and the samples has to produce *both*, with
identical window settings, or the comparison it exists for is not available.
"""

from __future__ import annotations

import random

import pytest

from evo.embeddings.__main__ import ALLELES, build_parser, main, shard_name
from evo.embeddings.extract import KmerEmbedder
from evo.embeddings.store import load

# --- fixtures -----------------------------------------------------------------

HEADER = """\
##fileformat=VCFv4.1
##INFO=<ID=SVTYPE,Number=1,Type=String,Description="Type">
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\tS2
"""
FMT = "GT:LN:ID:RAL:AAL:CO"
UNCALLED = "./.:0:NaN:NAN:NAN:NAN"


@pytest.fixture
def fasta(tmp_path):
    """A real FASTA on disk -- main() opens a path, not a Reference object."""
    rng = random.Random(11)
    seq = "".join(rng.choice("ACGT") for _ in range(4000))
    p = tmp_path / "ref.fa"
    p.write_text(">chr1\n" + "\n".join(seq[i:i + 60] for i in range(0, len(seq), 60)) + "\n")
    return str(p)


@pytest.fixture
def vcf(tmp_path):
    """Three breakpoints, five calls: 1000 and 3000 are called in both samples."""
    rows = []
    for pos, a, b in [(1000, "AAAA", "AAAAAA"), (2000, "CCCCC", None), (3000, "GGG", "GGGG")]:
        cells = [
            UNCALLED if ins is None
            else f"0/1:{len(ins)}:v{pos}_{i}:G:G{ins}:chr1_{pos}-chr1_{pos}"
            for i, ins in enumerate((a, b))
        ]
        rows.append(
            f"chr1\t{pos}\tREC\tG\tGAAA\t.\tPASS\tSVTYPE=INS\t{FMT}\t"
            + "\t".join(cells) + "\n"
        )
    p = tmp_path / "calls.vcf"
    p.write_text(HEADER + "".join(rows))
    return str(p)


@pytest.fixture
def kmer(monkeypatch):
    """Swap Evo 2 for the k-mer stand-in, so the whole command runs on a laptop."""
    monkeypatch.setattr(
        "evo.embeddings.__main__.Evo2Embedder",
        lambda model, device, use_kernels=False: KmerEmbedder(k=2),
    )


SMALL = ["--flank", "200", "--junction", "16", "--layers", "blocks.1", "--quiet"]


# --- shard_name ---------------------------------------------------------------

def test_a_whole_vcf_run_uses_the_plain_name():
    assert shard_name("alt") == "alt.npz"


def test_a_bounded_shard_carries_its_range():
    assert shard_name("alt", 2000, 2000) == "alt.2000-4000.npz"


def test_an_open_ended_shard_says_so():
    assert shard_name("reference", 2000, None) == "reference.2000-end.npz"


def test_offset_zero_with_a_limit_is_still_a_shard():
    """--limit alone bounds the run, so it must not claim the whole-VCF name."""
    assert shard_name("alt", 0, 137) == "alt.0-137.npz"


def test_shards_never_collide_in_one_directory():
    names = {shard_name(a, o, 2000) for a in ALLELES for o in (0, 2000, 4000)}
    assert len(names) == 6


# --- parser -------------------------------------------------------------------

def test_alleles_defaults_to_both():
    args = build_parser().parse_args(["a.vcf", "ref.fa", "out/"])
    assert args.alleles == "both"


def test_shared_window_flags_are_present():
    """They come from cli.add_shared_options; if that link breaks, so does the
    guarantee that the two files were cut the same way."""
    args = build_parser().parse_args(["a.vcf", "ref.fa", "out/", "--flank", "512"])
    assert (args.flank, args.junction, args.offset, args.limit) == (512, 64, 0, None)


def test_an_unknown_allele_is_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["a.vcf", "ref.fa", "out/", "--alleles", "novel"])


# --- dry run ------------------------------------------------------------------

def test_dry_run_makes_the_directory_but_writes_nothing(tmp_path, vcf, fasta):
    out = tmp_path / "out"
    assert main([vcf, fasta, str(out), "--dry-run", *SMALL]) == 0
    assert out.is_dir()
    assert list(out.iterdir()) == []


# --- the real thing -----------------------------------------------------------

def test_both_alleles_are_written(tmp_path, vcf, fasta, kmer):
    out = tmp_path / "out"
    assert main([vcf, fasta, str(out), *SMALL]) == 0
    assert sorted(p.name for p in out.glob("*.npz")) == ["alt.npz", "reference.npz"]


def test_the_reference_file_is_one_row_per_breakpoint(tmp_path, vcf, fasta, kmer):
    main([vcf, fasta, str(out := tmp_path / "out"), *SMALL])
    ref = load(str(out / "reference.npz"))
    assert len(ref) == 3
    assert ref.attrs["allele"] == "reference"
    assert list(ref.meta["pos"]) == [1000, 2000, 3000]
    assert set(ref.meta["sample"]) == {""}
    assert set(ref.meta["insert_length"]) == {0}


def test_the_alt_file_is_one_row_per_call(tmp_path, vcf, fasta, kmer):
    main([vcf, fasta, str(out := tmp_path / "out"), *SMALL])
    alt = load(str(out / "alt.npz"))
    assert len(alt) == 5
    assert alt.attrs["allele"] == "alt"
    assert sorted(alt.meta["sample"]) == ["S1", "S1", "S1", "S2", "S2"]
    assert all(n > 0 for n in alt.meta["insert_length"])


def test_every_alt_breakpoint_has_a_reference_window(tmp_path, vcf, fasta, kmer):
    """What the pair is for: `analysis --delta` joins them on (chrom, pos), and
    an alt row with no background row is silently dropped there."""
    main([vcf, fasta, str(out := tmp_path / "out"), *SMALL])
    alt, ref = load(str(out / "alt.npz")), load(str(out / "reference.npz"))
    bg = set(zip(ref.meta["chrom"], ref.meta["pos"]))
    assert set(zip(alt.meta["chrom"], alt.meta["pos"])) <= bg


def test_the_two_files_share_one_window_spec(tmp_path, vcf, fasta, kmer):
    """The reason both alleles come out of one command rather than two."""
    main([vcf, fasta, str(out := tmp_path / "out"), "--flank", "256", "--junction", "16",
          "--layers", "blocks.1", "--quiet"])
    alt, ref = load(str(out / "alt.npz")), load(str(out / "reference.npz"))
    shared = ("flank", "junction", "repeat_crop", "pooling", "model")
    assert {k: alt.attrs[k] for k in shared} == {k: ref.attrs[k] for k in shared}
    assert alt.attrs["flank"] == "256"
    assert alt.layers == ref.layers and alt.segments == ref.segments


def test_the_model_is_loaded_once_for_both_alleles(tmp_path, vcf, fasta, monkeypatch):
    """A 13 GB checkpoint fetch and ~10 s of warm load per process is the whole
    cost argument for doing this in one command."""
    loads = []
    monkeypatch.setattr(
        "evo.embeddings.__main__.Evo2Embedder",
        lambda model, device, use_kernels=False: (loads.append(model), KmerEmbedder(k=2))[1],
    )
    main([vcf, fasta, str(tmp_path / "out"), *SMALL])
    assert len(loads) == 1


@pytest.mark.parametrize("allele", ALLELES)
def test_a_single_allele_can_be_asked_for(tmp_path, vcf, fasta, kmer, allele):
    out = tmp_path / "out"
    main([vcf, fasta, str(out), "--alleles", allele, *SMALL])
    assert [p.name for p in out.glob("*.npz")] == [f"{allele}.npz"]


def test_the_reference_half_runs_first(tmp_path, vcf, fasta, kmer, capsys):
    """It is a third of the cost, so a worker that dies mid-run has already
    produced the control, and a bad flag surfaces on the cheap pass."""
    main([vcf, fasta, str(tmp_path / "out"), "--flank", "200", "--junction", "16",
          "--layers", "blocks.1"])
    err = capsys.readouterr().err
    assert err.index("[reference]") < err.index("[alt]")


def test_two_shards_coexist_in_one_directory(tmp_path, vcf, fasta, kmer):
    out = tmp_path / "out"
    main([vcf, fasta, str(out), "--offset", "0", "--limit", "2", *SMALL])
    main([vcf, fasta, str(out), "--offset", "2", "--limit", "2", *SMALL])
    assert sorted(p.name for p in out.glob("alt*.npz")) == [
        "alt.0-2.npz", "alt.2-4.npz",
    ]
    assert len(load(str(out / "alt.0-2.npz"))) == 2
