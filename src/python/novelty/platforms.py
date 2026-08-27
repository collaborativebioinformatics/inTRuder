"""Reading reference tandem-repeat catalogues from any of several platforms.

A *platform* is where a catalogue comes from (UCSC, TRExplorer, ...); a *format*
is how its file is laid out on disk. They vary independently -- TRExplorer ships
the same loci as a plain BED and as a TRGT BED -- so they are separate knobs and
the format is sniffed from the file by default.

Every reader returns a :class:`pandas.DataFrame` in one normalised schema:

    chrom   contig name, UCSC style (``chr1``)
    start   0-based, inclusive
    end     0-based, exclusive
    motif   the repeat unit, upper case

plus whichever of :data:`ANNOTATION_COLUMNS` the platform actually carries. That
optionality is the point: UCSC's Tandem Repeat Finder output has ``perMatch``
and ``copyNum``, a BED catalogue has only location and motif, and downstream
code must not assume either.

Supported platforms
-------------------
``ucsc``
    The ``simpleRepeat`` track -- Tandem Repeat Finder run over the reference by
    UCSC. Schema:
    https://genome.ucsc.edu/cgi-bin/hgTables?db=hg38&hgta_group=rep&hgta_track=simpleRepeat&hgta_table=simpleRepeat&hgta_doSchema=describe+table+schema
    Reads both the raw ``simpleRepeat.txt.gz`` database dump (17 fixed columns,
    no header) and an hgTables export (leading ``#bin  chrom  ...`` header, and
    possibly a subset of the columns).

``trexplorer``
    The genome-wide TR catalog behind https://trexplorer.broadinstitute.org
    (Weisburd, Dolzhenko et al.), 5.6M loci in v2.0. Location and motif only.

``bed``
    Any other BED4 catalogue: ``chrom start end motif``. The escape hatch for a
    platform that has no adapter here.

COORDINATES
-----------
Both ``simpleRepeat`` and the BED catalogues are 0-based half-open, and that is
what the normalised schema uses. VCF ``POS`` is 1-based; mixing the two silently
shifts every interval by one base, so conversion happens once, at the edges --
see :func:`novelty.catalog.to_internal`.
"""

from __future__ import annotations

import gzip
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# The normalised schema every reader produces.
CATALOG_COLUMNS = ("chrom", "start", "end", "motif")

# Optional per-repeat annotations, kept when the platform provides them:
#   period          length of the repeat unit (e.g. 6 -> 6 bp motif)
#   copy_num        mean number of copies of the unit in the reference
#   consensus_size  length of the consensus sequence (usually == period)
#   per_match       % identity between the perfect repeat and the genome
#   per_indel       % indel between the perfect repeat and the genome
ANNOTATION_COLUMNS = ("period", "copy_num", "consensus_size", "per_match", "per_indel")

CACHE_ENV = "NOVELTY_CACHE"


def default_cache() -> Path:
    """Where downloaded catalogues live, resolved at call time.

    Inside a checkout (including the editable install ``uv sync`` makes) that is
    the repo's own ``data/reference/``, so the files sit with the rest of the
    data. Installed anywhere else there is no repo to write into, so it falls
    back to the user cache directory. ``NOVELTY_CACHE`` overrides both.
    """
    override = os.environ.get(CACHE_ENV)
    if override:
        return Path(override).expanduser()
    here = Path(__file__).resolve()
    if len(here.parents) > 3 and (here.parents[3] / "data").is_dir():
        return here.parents[3] / "data" / "reference"
    fallback = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(fallback) / "novelty"


# --------------------------------------------------------------------------- #
# contigs
# --------------------------------------------------------------------------- #

def normalize_chrom(chrom: str) -> str:
    """Map a contig name onto UCSC style (``1`` -> ``chr1``, ``MT`` -> ``chrM``)."""
    name = str(chrom).strip()
    if not name.startswith("chr"):
        name = "chr" + name
    if name in ("chrMT", "chrmt"):
        name = "chrM"
    return name


def normalize_chroms(values) -> pd.Series:
    """Vectorised :func:`normalize_chrom`; contig names repeat, so map the uniques."""
    series = pd.Series(values, dtype=object).fillna("")
    codes, uniques = pd.factorize(series, sort=False)
    lookup = [normalize_chrom(u) for u in uniques] + [""]
    return pd.Series(
        [lookup[c if c >= 0 else -1] for c in codes], index=series.index, dtype=object
    )


# --------------------------------------------------------------------------- #
# file sniffing
# --------------------------------------------------------------------------- #

def _is_gzip(path: Path) -> bool:
    """Detect gzip by magic bytes -- a UCSC export is often ``.txt`` but gzipped."""
    with open(path, "rb") as handle:
        return handle.read(2) == b"\x1f\x8b"


def open_text(path: str | os.PathLike[str]):
    """Open a possibly-gzipped text file for reading."""
    path = Path(path)
    opener = gzip.open if _is_gzip(path) else open
    return opener(path, "rt")


def _read_table(path: Path, **kwargs) -> pd.DataFrame:
    """``pd.read_csv`` with compression taken from the file, not from its name.

    hgTables happily serves a gzipped table called ``.txt``, and pandas' own
    inference goes by the suffix.
    """
    compression = "gzip" if _is_gzip(path) else None
    return pd.read_csv(path, sep="\t", compression=compression, **kwargs)


def _first_lines(path: Path) -> tuple[str | None, str | None]:
    """The first ``#`` comment line and the first data line, either may be ``None``."""
    comment: str | None = None
    with open_text(path) as handle:
        for line in handle:
            if not line.strip():
                continue
            if line.startswith("#"):
                if comment is None:
                    comment = line.rstrip("\n")
                continue
            return comment, line.rstrip("\n")
    return comment, None


# Full column layout of a raw ``simpleRepeat.txt.gz`` dump (no header line).
_SIMPLEREPEAT_LAYOUT = (
    "bin", "chrom", "chromStart", "chromEnd", "name", "period", "copyNum",
    "consensusSize", "perMatch", "perIndel", "score", "A", "C", "G", "T",
    "entropy", "sequence",
)

# UCSC column name -> normalised name. Columns absent from the file are simply
# not produced; `bin`, `name`, `score`, A/C/G/T and `entropy` are dropped -- they
# are not useful here and cost memory across a million rows.
_SIMPLEREPEAT_FIELDS = {
    "chrom": "chrom", "chromStart": "start", "chromEnd": "end", "sequence": "motif",
    "period": "period", "copyNum": "copy_num", "consensusSize": "consensus_size",
    "perMatch": "per_match", "perIndel": "per_indel",
}
_SIMPLEREPEAT_REQUIRED = ("chrom", "chromStart", "chromEnd", "sequence")

# Full IUPAC, so a catalogue that writes an ambiguous base in a consensus is
# still recognised as a BED of motifs rather than rejected as unidentifiable.
_DNA = set("ACGTUNRYSWKMBDHVacgtunryswkmbdhv")


def sniff_format(path: str | os.PathLike[str]) -> str:
    """Guess the on-disk format of a catalogue file.

    Returns one of ``simplerepeat``, ``trgt`` or ``bed``; raises ``ValueError``
    when the first data line looks like none of them.
    """
    path = Path(path)
    comment, line = _first_lines(path)
    if comment is not None and "chromStart" in comment:
        return "simplerepeat"
    if line is None:
        raise ValueError(f"{path}: no data lines to identify the catalogue format")

    fields = line.split("\t")
    if len(fields) >= 4 and "MOTIFS=" in fields[3]:
        return "trgt"
    if len(fields) == len(_SIMPLEREPEAT_LAYOUT) and fields[4] == "trf":
        return "simplerepeat"
    if len(fields) >= 4 and fields[3] and set(fields[3]) <= _DNA:
        return "bed"
    raise ValueError(
        f"{path}: cannot identify the catalogue format from {line[:120]!r}; "
        f"pass --format explicitly (one of {', '.join(sorted(READERS))})"
    )


# --------------------------------------------------------------------------- #
# readers
# --------------------------------------------------------------------------- #

def read_simplerepeat(path: str | os.PathLike[str]) -> pd.DataFrame:
    """Read a UCSC ``simpleRepeat`` dump or hgTables export."""
    path = Path(path)
    comment, _ = _first_lines(path)
    if comment is not None and "chromStart" in comment:
        columns = tuple(comment.lstrip("#").split("\t"))
        skiprows = 1
    else:
        columns = _SIMPLEREPEAT_LAYOUT
        skiprows = 0

    missing = [c for c in _SIMPLEREPEAT_REQUIRED if c not in columns]
    if missing:
        raise ValueError(f"{path}: simpleRepeat columns {missing} missing from {columns}")

    usecols = [c for c in columns if c in _SIMPLEREPEAT_FIELDS]
    frame = _read_table(
        path, header=None, names=columns, usecols=usecols,
        skiprows=skiprows, comment="#",
        dtype={"chrom": "string", "sequence": "string"}, na_filter=False,
    )
    return _finalize(frame.rename(columns=_SIMPLEREPEAT_FIELDS), path)


def read_bed(path: str | os.PathLike[str]) -> pd.DataFrame:
    """Read a BED4 catalogue: ``chrom start end motif``, extra columns ignored."""
    path = Path(path)
    frame = _read_table(
        path, header=None, comment="#", usecols=[0, 1, 2, 3],
        names=["chrom", "start", "end", "motif"],
        dtype={0: "string", 3: "string"}, na_filter=False,
    )
    return _finalize(frame, path)


def read_trgt(path: str | os.PathLike[str]) -> pd.DataFrame:
    """Read a TRGT-style BED: ``chrom start end ID=..;MOTIFS=..;STRUC=..``.

    A variation cluster lists several comma-separated motifs for one interval;
    each becomes its own row, since any of them makes the locus known.
    """
    path = Path(path)
    frame = _read_table(
        path, header=None, comment="#", usecols=[0, 1, 2, 3],
        names=["chrom", "start", "end", "info"],
        dtype={0: "string", 3: "string"}, na_filter=False,
    )
    motifs = frame.pop("info").str.extract(r"MOTIFS=([^;\s]+)", expand=False)
    frame["motif"] = motifs.str.split(",")
    frame = frame.explode("motif", ignore_index=True)
    return _finalize(frame.dropna(subset=["motif"]), path)


READERS: dict[str, Callable[[str | os.PathLike[str]], pd.DataFrame]] = {
    "simplerepeat": read_simplerepeat,
    "bed": read_bed,
    "trgt": read_trgt,
}


def _finalize(frame: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Normalise contigs, coordinates and motifs; drop unusable rows."""
    out = pd.DataFrame(index=frame.index)
    out["chrom"] = normalize_chroms(frame["chrom"])
    out["start"] = pd.to_numeric(frame["start"], errors="coerce").astype("Int64")
    out["end"] = pd.to_numeric(frame["end"], errors="coerce").astype("Int64")
    out["motif"] = frame["motif"].astype(object).fillna("").str.strip().str.upper()
    for column in ANNOTATION_COLUMNS:
        if column in frame.columns:
            out[column] = pd.to_numeric(frame[column], errors="coerce")

    usable = out["start"].notna() & out["end"].notna() & (out["motif"].str.len() > 0)
    dropped = int((~usable).sum())
    if dropped:
        print(f"[novelty] {path}: skipped {dropped:,} row(s) with no motif or coordinates",
              file=sys.stderr)
    out = out.loc[usable].reset_index(drop=True)
    out["start"] = out["start"].astype("int64")
    out["end"] = out["end"].astype("int64")
    return out


def read_catalog(path: str | os.PathLike[str], fmt: str = "auto") -> pd.DataFrame:
    """Read any supported catalogue file into the normalised schema."""
    if fmt == "auto":
        fmt = sniff_format(path)
    try:
        reader = READERS[fmt]
    except KeyError:
        raise ValueError(
            f"unknown catalogue format {fmt!r}; expected one of "
            f"{', '.join(sorted(READERS))} or 'auto'"
        ) from None
    return reader(path)


# --------------------------------------------------------------------------- #
# platform registry
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Platform:
    """Where a reference catalogue comes from and how to fetch it."""

    name: str
    description: str
    url: str                        # ``.format(db=...)``
    filename: str                   # ``.format(db=...)``
    fmt: str = "auto"
    assemblies: tuple[str, ...] = ()   # empty == whatever the host serves
    bundled: str | None = None      # ``.format(db=...)``, relative to ``data/novelty/``
    annotation_only: bool = False   # excluded from the combined novelty verdict

    def url_for(self, db: str) -> str:
        if self.assemblies and db not in self.assemblies:
            raise ValueError(
                f"{self.name} has no catalogue for {db}; available: "
                f"{', '.join(self.assemblies)}"
            )
        return self.url.format(db=db)

    def bundled_path(self, db: str) -> Path | None:
        """The copy kept in the repo's ``data/novelty/``, if this platform has one.

        Resolved the same way as :func:`default_cache`: catalogues are data, so
        they live under ``data/`` with the rest of it rather than inside the
        installed module. Outside a checkout there is nothing to point at, so
        this returns ``None`` and the caller falls back to ``--repeats``.
        """
        if self.bundled is None:
            return None
        if self.assemblies and db not in self.assemblies:
            return None
        here = Path(__file__).resolve()
        if len(here.parents) <= 3 or not (here.parents[3] / "data").is_dir():
            return None
        return here.parents[3] / "data" / "novelty" / self.bundled.format(db=db)

    def default_path(self, db: str, cache_dir: Path | None = None) -> Path:
        return (cache_dir or default_cache()) / self.name / self.filename.format(db=db)


_TREXPLORER_RELEASE = (
    "https://github.com/broadinstitute/trexplorer-catalog/releases/download/v2.0/"
    "TRExplorer.repeat_catalog_v2.hg38.1_to_1000bp_motifs.bed.gz"
)

PLATFORMS: dict[str, Platform] = {
    "ucsc": Platform(
        name="ucsc",
        description="UCSC simpleRepeat track (Tandem Repeat Finder on the reference)",
        url="https://hgdownload.soe.ucsc.edu/goldenPath/{db}/database/simpleRepeat.txt.gz",
        filename="{db}.simpleRepeat.txt.gz",
        fmt="simplerepeat",
    ),
    "trexplorer": Platform(
        name="trexplorer",
        description="TRExplorer genome-wide TR catalog v2.0 (5.6M loci)",
        url=_TREXPLORER_RELEASE,
        filename="{db}.trexplorer_v2.bed.gz",
        fmt="bed",
        assemblies=("hg38",),
    ),
    "pathogenic": Platform(
        name="pathogenic",
        description="83 known disease-associated TR loci (kept in data/novelty/; "
                    "annotation only, never folded into the combined verdict)",
        url="",
        filename="{db}.pathogenic.TRGT.bed",
        fmt="trgt",
        assemblies=("hg38",),
        bundled="pathogenic.{db}.TRGT.bed",
        annotation_only=True,
    ),
    "bed": Platform(
        name="bed",
        description="any local BED4 catalogue (chrom start end motif); no download",
        url="",
        filename="{db}.bed.gz",
        fmt="bed",
    ),
}


def get_platform(name: str) -> Platform:
    try:
        return PLATFORMS[name]
    except KeyError:
        raise ValueError(
            f"unknown platform {name!r}; expected one of {', '.join(PLATFORMS)}"
        ) from None


def ensure_table(platform: str | Platform = "ucsc", db: str = "hg38",
                 path: str | os.PathLike[str] | None = None, *, download: bool = True,
                 cache_dir: str | os.PathLike[str] | None = None) -> Path:
    """Return a local catalogue file, fetching it from the platform if missing."""
    platform = get_platform(platform) if isinstance(platform, str) else platform
    if path is None:
        # A catalogue small enough to keep in the repo needs neither a download
        # nor a cache entry, and keeping it there means the tool works offline
        # and pins the exact version the results were produced against.
        bundled = platform.bundled_path(db)
        if bundled is not None and bundled.exists():
            return bundled
    target = (Path(path) if path
              else platform.default_path(db, Path(cache_dir) if cache_dir else None))
    if target.exists():
        return target
    if not download or not platform.url:
        raise FileNotFoundError(
            f"{target} not found (pass --repeats"
            f"{', or drop --no-download to fetch it' if platform.url else ''})"
        )

    url = platform.url_for(db)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    print(f"[novelty] downloading {url} -> {target}", file=sys.stderr)
    try:
        urllib.request.urlretrieve(url, tmp)
    except (urllib.error.URLError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        # A stock macOS framework Python has no CA bundle, so https fails here
        # even though the network is fine. curl is the shortest way out.
        raise RuntimeError(
            f"could not download {url}: {exc}\n"
            f"fetch it by hand and re-run, e.g.:\n"
            f"    mkdir -p {target.parent}\n"
            f"    curl -L -o {target} {url}"
        ) from exc
    tmp.replace(target)
    return target
