"""Load the STRchive disease-locus catalog and index it by position.

STRchive (https://strchive.org, https://github.com/dashnowlab/STRchive) curates
the known pathogenic tandem-repeat loci -- 82 of them as of v2.26.0 -- with
coordinates in three reference builds, the motifs seen at each locus, and the
copy-number ranges that separate benign from pathogenic alleles.

We need exactly one 500 KB file out of that 160 MB repository, so rather than
vendoring it as a submodule this module downloads ``STRchive-loci.json`` at a
pinned release tag, verifies its SHA-256, and caches it under
``data/reference/strchive/``. The tag travels into every annotated output, so
a result always names the catalog release it was scored against.

COORDINATES
-----------
STRchive's ``start_*``/``stop_*`` are BED style: 0-based, half-open. VCF ``POS``
is 1-based, so mixing the two shifts every interval by a base. Loci are stored
here in the on-disk 0-based half-open form; converting the *query* is the
caller's job (see ``compare.Query``).

MOTIFS
------
``*_reference_orientation`` fields hold motifs on the + strand of the reference,
which is the orientation an insertion sequence is reported in. The parallel
``*_gene_orientation`` fields are flipped for genes on the - strand and are not
used here.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from intruder.trcore.coords import interval_distance, normalize_chrom
from intruder.trcore.fetch import cache_root, download_bytes
from intruder.trcore.motifs import MotifEquivalence, canonical_motif

#: How this step decides two motifs are the same repeat.
#:
#: STRchive lists every locus in reference orientation, but a query motif comes
#: from TRF run on an SV insertion and may be called off either strand, so a
#: motif is folded onto its reverse complement by default -- a CAG expansion
#: reported as CTG is the same locus. ``--stranded`` builds the same policy with
#: ``reverse_complement=False`` and keeps the two strands apart.
#:
#: Note this differs from :data:`trcore.motifs.DEFAULT_EQUIVALENCE`, which the
#: novelty screen uses: that step screens against genome-wide catalogues where
#: folding strands also merges the homopolymers A and T, which it does not want.
CATALOG_EQUIVALENCE = MotifEquivalence(circular=True, reverse_complement=True)


def equivalence_for(stranded: bool) -> MotifEquivalence:
    """The motif-equivalence policy implied by the ``--stranded`` flag."""
    return MotifEquivalence(circular=True, reverse_complement=not stranded)

#: Release this module is pinned to. Bump deliberately, together with the hash.
STRCHIVE_VERSION = "v2.26.0"

#: SHA-256 of ``STRchive-loci.json`` at ``STRCHIVE_VERSION``.
STRCHIVE_SHA256 = "306618801d03bb48eb69a206a9ea3d83dbbcc1317f7673a6f694c7de0b227794"

_URL = ("https://raw.githubusercontent.com/dashnowlab/STRchive/"
        "{version}/data/STRchive-loci.json")

#: Overrides where the catalog is cached, the way ``NOVELTY_CACHE`` does for the
#: novelty screen.
CACHE_ENV = "STRCHIVE_CACHE"


def default_cache() -> Path:
    """Where the downloaded catalog lands -- see :func:`trcore.fetch.cache_root`.

    Inside a checkout that is ``data/reference/strchive/``, beside the catalogues
    the novelty screen downloads; outside one it falls back to the user cache.
    """
    return cache_root("intruder", env_var=CACHE_ENV) / "strchive"

#: Reference builds, mapped onto the field suffix STRchive uses for each.
BUILDS = {"hg38": "hg38", "hg19": "hg19", "t2t": "t2t", "chm13": "t2t"}

#: Motif classes, most to least clinically interesting. ``compare`` reports the
#: first class a query motif matches, so the order here is the priority order.
MOTIF_CLASSES = ("pathogenic", "reference", "benign", "unknown", "interruption")


@dataclass(frozen=True)
class DiseaseLocus:
    """One STRchive locus, with coordinates resolved to a single build."""

    id: str
    gene: str
    chrom: str
    start: int                        # 0-based, inclusive
    end: int                          # 0-based, exclusive
    disease: str
    disease_id: str
    inheritance: tuple[str, ...]
    evidence: tuple[str, ...]
    location_in_gene: str
    gene_strand: str
    ref_copies: float | None
    motif_len: int | None
    #: STRchive's own flag: is the *pathogenic* motif present in hg38 at all?
    #: ``"novel"`` marks loci where disease comes from a motif the reference
    #: does not carry -- the same idea as our own motif-novelty call.
    novel: str | None
    benign_min: int | None
    benign_max: int | None
    intermediate_min: int | None
    intermediate_max: int | None
    pathogenic_min: int | None
    pathogenic_max: int | None
    #: class name -> motifs as written by STRchive, in reference orientation
    motifs: dict[str, tuple[str, ...]]
    #: class name -> canonical keys of those motifs, for equivalence testing
    canonical: dict[str, tuple[str, ...]] = field(compare=False, repr=False)

    @property
    def length(self) -> int:
        return self.end - self.start

    def distance_to(self, start: int, end: int) -> int:
        """Distance in bp from a 0-based half-open interval; ``0`` when overlapping."""
        return interval_distance(start, end, self.start, self.end)

    def allele_class(self, copies: float | None) -> str:
        """Place a copy number in STRchive's ranges for this locus.

        Checked pathogenic-first: the ranges can overlap at their edges, and a
        call that could be read either way should surface as the actionable one.
        Returns ``"unknown"`` when ``copies`` is missing or falls in no
        annotated range.
        """
        if copies is None:
            return "unknown"
        for name, lo, hi in (
            ("pathogenic", self.pathogenic_min, self.pathogenic_max),
            ("intermediate", self.intermediate_min, self.intermediate_max),
            ("benign", self.benign_min, self.benign_max),
        ):
            if lo is None and hi is None:
                continue
            if (lo is None or copies >= lo) and (hi is None or copies <= hi):
                return name
        return "unknown"


def _as_tuple(value) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(str(v) for v in value if v)


def _locus_from_record(record: dict, suffix: str) -> DiseaseLocus | None:
    """Build a ``DiseaseLocus`` for one build, or ``None`` if it lacks coordinates."""
    start, end = record.get(f"start_{suffix}"), record.get(f"stop_{suffix}")
    if start is None or end is None:
        return None

    motifs = {
        cls: _as_tuple(record.get(f"{cls}_motif_reference_orientation"))
        for cls in MOTIF_CLASSES if cls != "interruption"
    }
    # The interruption field is not suffixed with "_motif".
    motifs["interruption"] = _as_tuple(record.get("interruption_reference_orientation"))
    canonical = {
        cls: tuple(dict.fromkeys(canonical_motif(m, CATALOG_EQUIVALENCE) for m in seqs))
        for cls, seqs in motifs.items()
    }

    return DiseaseLocus(
        id=str(record.get("id") or ""),
        gene=str(record.get("gene") or ""),
        chrom=normalize_chrom(record.get("chrom") or ""),
        start=int(start),
        end=int(end),
        disease=str(record.get("disease") or ""),
        disease_id=str(record.get("disease_id") or ""),
        inheritance=_as_tuple(record.get("inheritance")),
        evidence=_as_tuple(record.get("evidence")),
        location_in_gene=str(record.get("location_in_gene") or ""),
        gene_strand=str(record.get("gene_strand") or ""),
        ref_copies=None if record.get("ref_copies") is None else float(record["ref_copies"]),
        motif_len=None if record.get("motif_len") is None else int(record["motif_len"]),
        novel=record.get("novel"),
        benign_min=record.get("benign_min"),
        benign_max=record.get("benign_max"),
        intermediate_min=record.get("intermediate_min"),
        intermediate_max=record.get("intermediate_max"),
        pathogenic_min=record.get("pathogenic_min"),
        pathogenic_max=record.get("pathogenic_max"),
        motifs=motifs,
        canonical=canonical,
    )


class Catalog:
    """The STRchive loci for one reference build, indexed by contig.

    At 82 loci -- at most 10 on any one contig -- a per-contig linear scan is
    faster than building an interval tree and keeps this module dependency-free.
    """

    def __init__(self, loci: list[DiseaseLocus], *, build: str = "hg38",
                 version: str = STRCHIVE_VERSION) -> None:
        self.build = build
        self.version = version
        self.loci = sorted(loci, key=lambda l: (l.chrom, l.start))
        self._by_chrom: dict[str, list[DiseaseLocus]] = {}
        for locus in self.loci:
            self._by_chrom.setdefault(locus.chrom, []).append(locus)

    def __len__(self) -> int:
        return len(self.loci)

    def __iter__(self):
        return iter(self.loci)

    @classmethod
    def from_file(cls, path: str | os.PathLike[str], *, build: str = "hg38",
                  version: str = STRCHIVE_VERSION) -> Catalog:
        """Parse a ``STRchive-loci.json`` already on disk."""
        suffix = BUILDS.get(build)
        if suffix is None:
            raise ValueError(f"unknown build {build!r}; expected one of {sorted(BUILDS)}")
        with open(path, encoding="utf-8") as handle:
            records = json.load(handle)
        loci = [locus for locus in (_locus_from_record(r, suffix) for r in records)
                if locus is not None]
        return cls(loci, build=build, version=version)

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None, *, build: str = "hg38",
             version: str = STRCHIVE_VERSION, cache_dir: str | os.PathLike[str] | None = None,
             verbose: bool = True) -> Catalog:
        """Load the catalog, downloading and caching it if needed."""
        if path is None:
            path = fetch(version=version, cache_dir=cache_dir, verbose=verbose)
        return cls.from_file(path, build=build, version=version)

    def nearby(self, chrom: str, start: int, end: int, window: int = 0) -> list[DiseaseLocus]:
        """Loci within ``window`` bp of the 0-based half-open interval, nearest first."""
        chrom = normalize_chrom(chrom)
        hits = [(locus.distance_to(start, end), locus)
                for locus in self._by_chrom.get(chrom, ())]
        hits = [(d, locus) for d, locus in hits if d <= window]
        hits.sort(key=lambda pair: (pair[0], pair[1].start))
        return [locus for _, locus in hits]

    def by_id(self, locus_id: str) -> DiseaseLocus | None:
        for locus in self.loci:
            if locus.id == locus_id:
                return locus
        return None



def fetch(*, version: str = STRCHIVE_VERSION,
          cache_dir: str | os.PathLike[str] | None = None,
          force: bool = False, verbose: bool = True) -> Path:
    """Download ``STRchive-loci.json`` at ``version``, returning the cached path.

    The checksum is only pinned for the default release; asking for another
    version downloads it but cannot verify it, and says so.
    """
    cache_dir = Path(cache_dir) if cache_dir is not None else default_cache()
    target = cache_dir / f"STRchive-loci.{version}.json"
    if target.exists() and not force:
        return target

    url = _URL.format(version=version)
    if verbose:
        print(f"[strchive] downloading {url}", file=sys.stderr)
    payload = download_bytes(url, label="strchive")

    digest = hashlib.sha256(payload).hexdigest()
    if version == STRCHIVE_VERSION and digest != STRCHIVE_SHA256:
        raise RuntimeError(
            f"checksum mismatch for {url}\n  expected {STRCHIVE_SHA256}\n  got      {digest}"
        )
    if version != STRCHIVE_VERSION and verbose:
        print(f"[strchive] {version} is not the pinned release "
              f"({STRCHIVE_VERSION}); checksum unverified, sha256={digest}", file=sys.stderr)

    cache_dir.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    if verbose:
        print(f"[strchive] cached -> {target} ({len(payload) / 1e3:.0f} kB)", file=sys.stderr)
    return target
