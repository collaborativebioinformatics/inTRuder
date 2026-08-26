"""Novelty assessment for tandem repeats found in SV insertions.

A tandem repeat called inside an SV insertion is *novel* when the reference
genome has nothing like it at that locus. Which reference, though, depends on
the catalogue: UCSC's ``simpleRepeat`` track and the TRExplorer catalog disagree
about plenty of loci, so the screen is written against a normalised schema and
any number of catalogues can be screened at once.

    novelty.motifs      strand- and phase-independent motif comparison
    novelty.platforms   reading a catalogue from UCSC, TRExplorer or a BED file
    novelty.catalog     the interval index and the known/novel verdict
    novelty.insertions  purity of the insertion itself, and the filters on it
    novelty.cli         the `python -m novelty` command line
"""

from .catalog import (
    STATUSES,
    Hit,
    ReferenceRepeat,
    RepeatCatalog,
    Verdict,
    to_external,
    to_internal,
)
from .insertions import Check, add_insertion_purity, filter_reasons, union_length
from .motifs import (
    MAX_FUZZY_MOTIF,
    canonical_motif,
    canonical_motifs,
    least_rotation,
    motif_distance,
    primitive_unit,
    reverse_complement,
)
from .platforms import (
    ANNOTATION_COLUMNS,
    CACHE_ENV,
    CATALOG_COLUMNS,
    PLATFORMS,
    Platform,
    default_cache,
    ensure_table,
    normalize_chrom,
    normalize_chroms,
    read_catalog,
    sniff_format,
)

__all__ = [
    "ANNOTATION_COLUMNS",
    "CACHE_ENV",
    "CATALOG_COLUMNS",
    "MAX_FUZZY_MOTIF",
    "PLATFORMS",
    "STATUSES",
    "Check",
    "Hit",
    "Platform",
    "ReferenceRepeat",
    "RepeatCatalog",
    "RepeatFilter",
    "Verdict",
    "add_insertion_purity",
    "canonical_motif",
    "canonical_motifs",
    "default_cache",
    "ensure_table",
    "filter_reasons",
    "least_rotation",
    "motif_distance",
    "normalize_chrom",
    "normalize_chroms",
    "primitive_unit",
    "read_catalog",
    "reverse_complement",
    "sniff_format",
    "to_external",
    "to_internal",
    "union_length",
]
