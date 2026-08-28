"""Locating the checkout a module runs from."""

from intruder.trcore.paths import MARKERS, repo_root


def _make_checkout(root):
    root.mkdir(parents=True, exist_ok=True)
    for marker in MARKERS:
        (root / marker).mkdir() if marker == "data" else (root / marker).touch()
    return root


def test_finds_the_root_from_a_file_nested_inside_it(tmp_path):
    root = _make_checkout(tmp_path / "repo")
    deep = root / "src" / "python" / "intruder" / "pipeline" / "novelty"
    deep.mkdir(parents=True)
    assert repo_root(deep / "platforms.py") == root


def test_depth_does_not_matter(tmp_path):
    """The whole point: moving a module deeper must not change the answer."""
    root = _make_checkout(tmp_path / "repo")
    shallow = root / "a"
    deeper = root / "a" / "b" / "c" / "d" / "e"
    deeper.mkdir(parents=True)
    assert repo_root(shallow / "m.py") == repo_root(deeper / "m.py") == root


def test_returns_none_outside_a_checkout(tmp_path):
    """An installed wheel in site-packages has no repo above it."""
    loose = tmp_path / "site-packages" / "intruder"
    loose.mkdir(parents=True)
    assert repo_root(loose / "trcore.py") is None


def test_a_partial_match_is_not_a_checkout(tmp_path):
    """Every marker must be present -- a stray pyproject.toml is not enough."""
    almost = tmp_path / "not-a-repo"
    (almost / "src").mkdir(parents=True)
    (almost / "pyproject.toml").touch()  # no data/
    assert repo_root(almost / "src" / "m.py") is None


def test_the_nearest_root_wins(tmp_path):
    """A checkout vendored inside another resolves to the inner one."""
    outer = _make_checkout(tmp_path / "outer")
    inner = _make_checkout(outer / "vendor" / "inner")
    assert repo_root(inner / "m.py") == inner
