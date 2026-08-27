"""Primitives shared by every tandem-repeat pipeline step.

Steps in this repository talk to each other through files, not imports, and
that stays true: nothing here knows about a catalogue, a caller, or a file
format. What lives in this package is the small set of definitions that were
provably identical across steps and that are wrong in the same way when they
are wrong -- how a motif is reduced to a comparable key, how far off two motifs
may be and still be the same repeat, how a coordinate is converted and measured,
and where a downloaded catalogue is cached.

Duplicating those is not a harmless copy. Two steps that disagree by one base
on what "overlapping" means, or that fold strands differently, produce tables
that look comparable and are not.

Deliberately *not* here: anything catalogue-shaped. ``novelty.catalog`` is a
numpy columnar index over millions of reference repeats with an on-disk cache;
``strchive.catalog`` is 82 JSON records carrying disease semantics. They share
three field names and no behaviour, and merging them would force pure-stdlib
code to import pandas to look up a disease locus.

This package is pure standard library. Vectorised wrappers for catalogue-scale
data live with the step that needs them (see ``novelty.platforms``).
"""

from .coords import interval_distance, normalize_chrom, to_external, to_internal
from .fetch import cache_root, download_bytes, download_file
from .motifs import (
    DEFAULT_EQUIVALENCE,
    DEFAULT_TOLERANCE,
    MATCH_EXACT,
    MATCH_FUZZY,
    MATCH_KINDS,
    MATCH_NONE,
    MATCH_SUBREPEAT,
    MATCH_VNTR,
    MAX_FUZZY_MOTIF,
    STR_MAX_MOTIF,
    MotifEquivalence,
    MotifMatch,
    MotifTolerance,
    canonical_motif,
    edit_budget,
    least_rotation,
    motif_distance,
    primitive_unit,
    reverse_complement,
    tiling_distance,
)

__all__ = [
    "DEFAULT_EQUIVALENCE",
    "DEFAULT_TOLERANCE",
    "MATCH_EXACT",
    "MATCH_FUZZY",
    "MATCH_KINDS",
    "MATCH_NONE",
    "MATCH_SUBREPEAT",
    "MATCH_VNTR",
    "MAX_FUZZY_MOTIF",
    "STR_MAX_MOTIF",
    "MotifEquivalence",
    "MotifMatch",
    "MotifTolerance",
    "cache_root",
    "canonical_motif",
    "download_bytes",
    "download_file",
    "edit_budget",
    "interval_distance",
    "least_rotation",
    "motif_distance",
    "normalize_chrom",
    "primitive_unit",
    "reverse_complement",
    "tiling_distance",
    "to_external",
    "to_internal",
]
