"""Novelty assessment for tandem repeats found in SV insertions.

A tandem repeat called inside an SV insertion is *novel* when the reference
genome has nothing like it at that locus. Which reference, though, depends on
the catalogue: UCSC's ``simpleRepeat`` track and the TRExplorer catalog disagree
about plenty of loci, so the screen is written against a normalised schema and
any number of catalogues can be screened at once.

    trcore.motifs       motif comparison: equivalence, and tolerance
    trcore.coords       the coordinate conventions both steps share
    novelty.platforms   reading a catalogue from UCSC, TRExplorer or a BED file
    novelty.catalog     the interval index and the known/novel verdict
    novelty.insertions  purity of the insertion itself, and the filters on it
    novelty.cli         the `python -m intruder.pipeline.novelty` command line
"""

from intruder.trcore.coords import interval_distance, normalize_chrom, to_external, to_internal
from intruder.trcore.motifs import (
    DEFAULT_EQUIVALENCE,
    DEFAULT_TOLERANCE,
    MATCH_KINDS,
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

from .catalog import (
    STATUSES,
    UNSCREENED,
    Hit,
    ReferenceRepeat,
    RepeatCatalog,
    RepeatFilter,
    Verdict,
)
from .insertions import Check, add_insertion_purity, filter_reasons, union_length
from .platforms import (
    ANNOTATION_COLUMNS,
    CACHE_ENV,
    CATALOG_COLUMNS,
    PLATFORMS,
    Platform,
    canonical_motifs,
    default_cache,
    ensure_table,
    normalize_chroms,
    read_catalog,
    sniff_format,
)

__all__ = [
    "ANNOTATION_COLUMNS",
    "CACHE_ENV",
    "CATALOG_COLUMNS",
    "DEFAULT_EQUIVALENCE",
    "DEFAULT_TOLERANCE",
    "MATCH_KINDS",
    "MAX_FUZZY_MOTIF",
    "PLATFORMS",
    "STATUSES",
    "STR_MAX_MOTIF",
    "UNSCREENED",
    "Check",
    "Hit",
    "MotifEquivalence",
    "MotifMatch",
    "MotifTolerance",
    "Platform",
    "ReferenceRepeat",
    "RepeatCatalog",
    "RepeatFilter",
    "Verdict",
    "add_insertion_purity",
    "canonical_motif",
    "canonical_motifs",
    "default_cache",
    "edit_budget",
    "ensure_table",
    "filter_reasons",
    "interval_distance",
    "least_rotation",
    "motif_distance",
    "normalize_chrom",
    "normalize_chroms",
    "primitive_unit",
    "read_catalog",
    "reverse_complement",
    "sniff_format",
    "tiling_distance",
    "to_external",
    "to_internal",
    "union_length",
]
