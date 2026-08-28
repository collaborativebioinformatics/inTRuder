"""Fetching a reference catalogue and caching it on disk.

No step vendors the catalogue it screens against: UCSC's ``simpleRepeat`` is a
30 MB blob, the TRExplorer release larger still, and STRchive lives in a 160 MB
repository we need one 500 KB file out of. So every step downloads on demand and
caches, and the two questions that raises -- *where does it land* and *how do we
survive a broken TLS trust store* -- have one answer here rather than one per
step.

TLS
---
Plenty of Python installs (python.org builds on macOS, some HPC modules) ship
without a usable CA bundle, which makes ``urllib`` fail on any https URL while
the system ``curl`` -- using the OS trust store -- succeeds. A pipeline step
should not die on that, so both helpers try Python first and shell out second,
rather than taking on ``certifi`` as a dependency.

Nothing here is catalogue-shaped: it moves bytes and picks directories, and the
callers know what the bytes mean.
"""

from __future__ import annotations

import os
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from intruder.trcore.paths import repo_root

#: Where the cache lands inside a checkout, relative to the repo root.
CACHE_SUBDIR = ("data", "reference")


def cache_root(fallback: str, *, env_var: str | None = None) -> Path:
    """Where downloaded catalogues live, resolved at call time.

    Inside a checkout (including the editable install ``uv sync`` makes) that is
    the repo's own ``data/reference/``, so the files sit with the rest of the
    data. Installed anywhere else there is no repo to write into, so it falls
    back to ``<user cache>/<fallback>``. ``env_var``, when set, overrides both.

    Callers append their own subdirectory, so two steps sharing a checkout do
    not collide inside ``data/reference/``.
    """
    if env_var:
        override = os.environ.get(env_var)
        if override:
            return Path(override).expanduser()
    root = repo_root(__file__)
    if root is not None:
        return root.joinpath(*CACHE_SUBDIR)
    user_cache = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(user_cache) / fallback


def _curl(url: str, label: str, reason: object, *,
          output: Path | None = None) -> bytes:
    """Retry a download through the system ``curl``. Returns b"" when ``output``."""
    curl = shutil.which("curl")
    if curl is None:
        raise RuntimeError(
            f"could not download {url}: {reason}\n"
            f"TLS verification failed and curl is not on PATH; fetch it by hand "
            f"and re-run, passing the local file."
        )
    print(f"[{label}] urllib TLS verification failed ({reason}); retrying with curl",
          file=sys.stderr)
    argv = [curl, "-sSfL", url] + (["-o", str(output)] if output else [])
    result = subprocess.run(argv, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"curl failed for {url}: {result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout


def download_bytes(url: str, *, label: str) -> bytes:
    """GET ``url`` into memory. For files small enough to checksum in one piece."""
    try:
        with urllib.request.urlopen(url) as response:
            return response.read()
    except urllib.error.URLError as exc:
        if not isinstance(exc.reason, ssl.SSLError):
            raise
        return _curl(url, label, exc.reason)


def download_file(url: str, target: str | os.PathLike[str], *, label: str) -> Path:
    """GET ``url`` to ``target``, streaming. For catalogues too big to hold in memory.

    Downloads to a ``.part`` sibling and renames on success, so an interrupted
    fetch never leaves a truncated file that a later run would trust.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    print(f"[{label}] downloading {url} -> {target}", file=sys.stderr)
    try:
        try:
            urllib.request.urlretrieve(url, tmp)
        except urllib.error.URLError as exc:
            if not isinstance(exc.reason, ssl.SSLError):
                raise
            _curl(url, label, exc.reason, output=tmp)
    except (urllib.error.URLError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"could not download {url}: {exc}\n"
            f"fetch it by hand and re-run, e.g.:\n"
            f"    mkdir -p {target.parent}\n"
            f"    curl -L -o {target} {url}"
        ) from exc
    tmp.replace(target)
    return target
