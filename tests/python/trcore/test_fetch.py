"""Cache placement and downloading -- run with `uv run pytest`.

Nothing here touches the network: the two entry points are exercised against a
stubbed ``urllib`` so the TLS-failure path, which is the whole reason this code
is shared, can actually be tested.
"""

from __future__ import annotations

import ssl
import subprocess
import urllib.error
from pathlib import Path

import pytest

from intruder.trcore import fetch
from intruder.trcore.fetch import cache_root, download_bytes, download_file

# --------------------------------------------------------------------------- #
# where the cache lands
# --------------------------------------------------------------------------- #

def test_cache_root_is_the_repo_data_directory():
    """Inside a checkout the catalogues belong with the rest of the data."""
    root = cache_root("anything")
    assert root.name == "reference"
    assert root.parent.name == "data"


def test_the_env_var_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_TR_CACHE", str(tmp_path))
    assert cache_root("anything", env_var="TEST_TR_CACHE") == tmp_path


def test_a_blank_env_var_is_ignored(monkeypatch):
    """An exported-but-empty variable must not send the cache to the root."""
    monkeypatch.setenv("TEST_TR_CACHE", "")
    assert cache_root("anything", env_var="TEST_TR_CACHE").name == "reference"


def test_the_env_var_is_only_read_when_named(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_TR_CACHE", str(tmp_path))
    assert cache_root("anything") != tmp_path


def test_falls_back_to_the_user_cache_outside_a_checkout(monkeypatch, tmp_path):
    """Installed outside a checkout there is no ``data/`` to write into."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(fetch, "__file__", str(tmp_path / "a/b/c/fetch.py"))
    assert cache_root("novelty") == tmp_path / "novelty"
    assert cache_root("intruder") == tmp_path / "intruder"


def test_two_steps_can_share_one_checkout_cache():
    """The root is shared; the subdirectory is the caller's to append."""
    assert cache_root("novelty") == cache_root("intruder")


# --------------------------------------------------------------------------- #
# downloading
# --------------------------------------------------------------------------- #

def _tls_error() -> urllib.error.URLError:
    return urllib.error.URLError(ssl.SSLError("CERTIFICATE_VERIFY_FAILED"))


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self) -> bytes:
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_download_bytes_returns_the_payload(monkeypatch):
    monkeypatch.setattr(fetch.urllib.request, "urlopen",
                        lambda url: _Response(b"payload"))
    assert download_bytes("https://example/x", label="test") == b"payload"


def test_download_bytes_falls_back_to_curl_on_a_tls_failure(monkeypatch, capsys):
    """A stock macOS framework Python has no CA bundle; the system curl does."""
    def boom(url):
        raise _tls_error()

    monkeypatch.setattr(fetch.urllib.request, "urlopen", boom)
    monkeypatch.setattr(fetch.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(fetch.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(
        argv, 0, stdout=b"from curl", stderr=b""))
    assert download_bytes("https://example/x", label="test") == b"from curl"
    assert "retrying with curl" in capsys.readouterr().err


def test_a_non_tls_error_is_not_retried(monkeypatch):
    """A 404 is a real failure; retrying it with curl only hides the reason."""
    def boom(url):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(fetch.urllib.request, "urlopen", boom)
    monkeypatch.setattr(fetch.shutil, "which",
                        lambda name: pytest.fail("curl must not be reached"))
    with pytest.raises(urllib.error.URLError):
        download_bytes("https://example/x", label="test")


def test_a_tls_failure_without_curl_says_so(monkeypatch):
    def boom(url):
        raise _tls_error()

    monkeypatch.setattr(fetch.urllib.request, "urlopen", boom)
    monkeypatch.setattr(fetch.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="curl is not on PATH"):
        download_bytes("https://example/x", label="test")


def test_a_failing_curl_reports_its_stderr(monkeypatch):
    def boom(url):
        raise _tls_error()

    monkeypatch.setattr(fetch.urllib.request, "urlopen", boom)
    monkeypatch.setattr(fetch.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(fetch.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(
        argv, 22, stdout=b"", stderr=b"404 Not Found"))
    with pytest.raises(RuntimeError, match="404 Not Found"):
        download_bytes("https://example/x", label="test")


def test_download_file_writes_the_target_and_makes_its_parent(monkeypatch, tmp_path):
    def retrieve(url, dest):
        Path(dest).write_bytes(b"catalogue")

    monkeypatch.setattr(fetch.urllib.request, "urlretrieve", retrieve)
    target = tmp_path / "nested" / "ucsc" / "hg38.txt.gz"
    assert download_file("https://example/x", target, label="test") == target
    assert target.read_bytes() == b"catalogue"


def test_download_file_leaves_no_partial_file_behind(monkeypatch, tmp_path):
    """An interrupted fetch must not leave a truncated file a later run trusts."""
    def retrieve(url, dest):
        Path(dest).write_bytes(b"half a cata")
        raise OSError("connection reset")

    monkeypatch.setattr(fetch.urllib.request, "urlretrieve", retrieve)
    target = tmp_path / "hg38.txt.gz"
    with pytest.raises(RuntimeError, match="could not download"):
        download_file("https://example/x", target, label="test")
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_download_file_falls_back_to_curl_on_a_tls_failure(monkeypatch, tmp_path):
    def retrieve(url, dest):
        raise _tls_error()

    def run(argv, **kw):
        Path(argv[argv.index("-o") + 1]).write_bytes(b"from curl")
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(fetch.urllib.request, "urlretrieve", retrieve)
    monkeypatch.setattr(fetch.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(fetch.subprocess, "run", run)
    target = tmp_path / "hg38.txt.gz"
    assert download_file("https://example/x", target, label="test") == target
    assert target.read_bytes() == b"from curl"
