"""Round-tripping vectors and their metadata."""

from __future__ import annotations

import numpy as np
import pytest

from evo.embeddings.store import load, save
from evo.embeddings.windows import WindowSpec, build_window
from evo.utils import DictReference

LAYERS = ["blocks.16", "blocks.31"]
SEGS = ["left", "repeat", "right"]


@pytest.fixture
def windows():
    ref = DictReference({"chr1": "ACGT" * 64, "chr2": "TTTT" * 64})
    spec = WindowSpec(flank=16, junction=4, repeat_crop=8)
    return [
        build_window(ref, "chr1", 64, "GGGG", spec),
        build_window(ref, "chr2", 128, "A" * 40, spec),  # cropped
    ]


@pytest.fixture
def vectors(windows):
    rng = np.random.default_rng(0)
    return rng.normal(size=(len(windows), len(LAYERS), len(SEGS), 8)).astype(np.float32)


def test_round_trip(tmp_path, windows, vectors):
    p = str(tmp_path / "e.npz")
    save(p, vectors, windows, LAYERS, SEGS,
         samples=["HG1", "HG2"], svids=["S.1", "S.2"])
    got = load(p)
    assert got.layers == LAYERS
    assert got.segments == SEGS
    assert len(got) == 2
    assert got.vectors.shape == vectors.shape
    # float16 on the way out, so compare with a tolerance that reflects it.
    assert got.vectors == pytest.approx(vectors, abs=1e-2)


def test_metadata_survives(tmp_path, windows, vectors):
    p = str(tmp_path / "e.npz")
    save(p, vectors, windows, LAYERS, SEGS,
         samples=["HG1", "HG2"], svids=["S.1", "S.2"])
    m = load(p).meta
    assert [str(c) for c in m["chrom"]] == ["chr1", "chr2"]
    assert m["pos"].tolist() == [64, 128]
    assert [str(s) for s in m["sample"]] == ["HG1", "HG2"]
    assert m["insert_length"].tolist() == [4, 40]
    assert m["cropped"].tolist() == [False, True]


def test_insert_length_is_pre_crop(tmp_path, windows, vectors):
    """The length covariate is what lets a cluster be checked against insertion
    size; storing the cropped length would defeat it."""
    p = str(tmp_path / "e.npz")
    save(p, vectors, windows, LAYERS, SEGS)
    assert load(p).meta["insert_length"].tolist()[1] == 40


def test_attrs_record_the_settings(tmp_path, windows, vectors):
    p = str(tmp_path / "e.npz")
    save(p, vectors, windows, LAYERS, SEGS, attrs={"model": "evo2_7b_base"})
    attrs = load(p).attrs
    assert attrs["model"] == "evo2_7b_base"


def test_view_selects_one_layer_and_segment(tmp_path, windows, vectors):
    p = str(tmp_path / "e.npz")
    save(p, vectors, windows, LAYERS, SEGS)
    got = load(p)
    assert got.view("blocks.31", "repeat").shape == (2, 8)
    assert got.view("blocks.31", "repeat") == pytest.approx(
        vectors[:, 1, 1, :], abs=1e-2
    )


@pytest.mark.parametrize("layer,segment", [("nope", "repeat"), ("blocks.16", "nope")])
def test_view_rejects_unknown_names(tmp_path, windows, vectors, layer, segment):
    p = str(tmp_path / "e.npz")
    save(p, vectors, windows, LAYERS, SEGS)
    with pytest.raises(KeyError, match="nope"):
        load(p).view(layer, segment)


def test_row_count_mismatch_is_caught_at_write_time(tmp_path, windows, vectors):
    """Better a loud error here than misaligned metadata discovered downstream."""
    with pytest.raises(ValueError, match="rows but"):
        save(str(tmp_path / "e.npz"), vectors[:1], windows, LAYERS, SEGS)


def test_axis_mismatch_is_caught_at_write_time(tmp_path, windows, vectors):
    with pytest.raises(ValueError, match="do not match"):
        save(str(tmp_path / "e.npz"), vectors, windows, LAYERS, ["left"])


def test_float16_overflow_is_named_per_layer_and_recorded(tmp_path, capsys):
    """The 2026-08-27 run shipped 22% inf and said nothing. Never again.

    One layer is given values beyond float16's 65504 range and the other is
    left small, so the report has to identify *which* layer went rather than
    just noticing that something did.
    """
    from evo.embeddings.store import load, save
    from evo.embeddings.windows import WindowSpec, build_window
    from evo.utils import DictReference

    ref = DictReference({"chr1": "ACGT" * 64})
    windows = [build_window(ref, "chr1", 128, "TT", WindowSpec(flank=16, junction=4))]
    vectors = np.ones((1, 2, 5, 8), dtype=np.float32)
    vectors[:, 1] = 1e6  # blocks.31's actual failure mode

    out = tmp_path / "over.npz"
    save(str(out), vectors, windows, ["blocks.26", "blocks.31"],
         ["left", "junction_5p", "repeat", "junction_3p", "right"])

    err = capsys.readouterr().err
    assert "blocks.31" in err and "100.0%" in err
    assert "blocks.26" not in err
    assert "re-run without blocks.31" in err

    back = load(str(out))
    assert back.attrs["overflowed_layers"] == "blocks.31"
    assert np.isfinite(back.view("blocks.26", "left")).all()


def test_no_overflow_leaves_the_attribute_empty_and_stderr_quiet(tmp_path, capsys):
    from evo.embeddings.store import load, save
    from evo.embeddings.windows import WindowSpec, build_window
    from evo.utils import DictReference

    ref = DictReference({"chr1": "ACGT" * 64})
    windows = [build_window(ref, "chr1", 128, "TT", WindowSpec(flank=16, junction=4))]
    out = tmp_path / "fine.npz"
    save(str(out), np.ones((1, 1, 5, 8), dtype=np.float32), windows,
         ["blocks.26"], ["left", "junction_5p", "repeat", "junction_3p", "right"])

    assert capsys.readouterr().err == ""
    assert load(str(out)).attrs["overflowed_layers"] == ""
