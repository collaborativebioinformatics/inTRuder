"""Finding and opening VCF files, confined to the data root.

The containment rule here is the counterpart of the SQL sandbox next door: agent
SQL gets no filesystem access at all, so the one tool that does open a file has to
be the narrow, checked path rather than the hole in the wall.
"""

from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any

from app.util.vcf.common import VCF_SUFFIXES, VcfScanError


def resolve_vcf_path(raw: str, root: Path) -> Path:
    """Resolve a user- or model-supplied path, confined to ``root``.

    The agent chooses this path, and the SQL sandbox next door deliberately has
    no filesystem access at all (`registry._materialize`). A tool that opens an
    arbitrary path would be the hole in that wall, so: resolve symlinks first,
    then require the result to sit under the data root, and accept only the
    suffixes this parser can actually read.
    """
    if not str(raw).strip():
        raise VcfScanError("no path given")

    root = root.resolve()
    candidate = Path(str(raw).strip()).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    # resolve() follows symlinks, so a link pointing out of the root fails the
    # containment check below rather than passing it.
    candidate = candidate.resolve()

    if not candidate.is_relative_to(root):
        raise VcfScanError(
            f"path is outside the data root ({root}); only files under it can be read"
        )
    if candidate.suffix == ".bcf" or candidate.name.endswith(".bcf.gz"):
        raise VcfScanError(
            "BCF is the binary encoding of a VCF and this reader is text-only; "
            "convert it first with `bcftools view -O v`"
        )
    if not candidate.name.endswith(VCF_SUFFIXES):
        raise VcfScanError(
            f"{candidate.name!r} is not a VCF; expected one of {', '.join(VCF_SUFFIXES)}"
        )
    if not candidate.is_file():
        raise VcfScanError(f"file not found: {candidate}")
    return candidate


def list_vcfs(root: Path, limit: int = 100) -> list[dict[str, Any]]:
    """Every VCF under ``root``, as paths relative to it, largest last.

    This is what makes the tool usable without the caller already knowing a path:
    a wrong or absent path comes back with this list rather than with a bare
    error, the way `describe_dataset` answers an unknown name with the known ones.
    """
    root = root.resolve()
    if not root.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if len(found) >= limit:
            break
        if not path.is_file() or not path.name.endswith(VCF_SUFFIXES):
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        found.append(
            {"path": str(path.relative_to(root)), "size_bytes": path.stat().st_size}
        )
    return found


def open_text(path: Path):
    """Open plain or gzipped VCF text, deciding by magic bytes not by suffix.

    bgzip output is gzip-compatible for a forward read, so a `.vcf.gz` from
    bcftools and one from `gzip` both work here.
    """
    with path.open("rb") as probe:
        gzipped = probe.read(2) == b"\x1f\x8b"
    if gzipped:
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("rt", encoding="utf-8", errors="replace")

