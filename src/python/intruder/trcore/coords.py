"""Coordinate conventions, in one place because getting them wrong is silent.

Every step here works in **0-based half-open** coordinates internally and
converts once at the edges. The inputs do not agree: VCF ``POS`` is 1-based, a
BED interval is 0-based half-open, and UCSC, TRExplorer and STRchive are all
BED-style. Mixing the two shifts every interval by exactly one base, which
produces output that is plausible, self-consistent, and wrong.
"""

from __future__ import annotations


def normalize_chrom(chrom: str) -> str:
    """Map a contig name onto UCSC style (``1`` -> ``chr1``, ``MT`` -> ``chrM``).

    Every catalogue this project reads -- UCSC, TRExplorer, STRchive -- names
    contigs this way, so normalising on the way in means a query never misses
    only because its caller wrote ``1`` instead of ``chr1``.
    """
    name = str(chrom).strip()
    if not name.startswith("chr"):
        name = "chr" + name
    if name in ("chrMT", "chrmt"):
        name = "chrM"
    return name


def to_internal(pos, coord_base: int):
    """Input coordinate -> 0-based. A 1-based VCF POS is the base before the insert."""
    return pos - 1 if coord_base == 1 else pos


def to_external(start, end, coord_base: int):
    """0-based half-open interval -> the caller's convention."""
    return (start + 1, end) if coord_base == 1 else (start, end)


def interval_distance(start: int, end: int, other_start: int, other_end: int) -> int:
    """Distance in bp between two 0-based half-open intervals; ``0`` when they overlap.

    Directly adjacent intervals are 1 bp apart, so a query landing on the base
    immediately after a repeat is reported at distance 1 rather than 0 -- the
    caller decides with a window whether that is close enough.
    """
    if end > other_start and start < other_end:
        return 0
    if start >= other_end:                  # query lies to the right
        return start - other_end + 1
    return other_start - end + 1            # query lies to the left
