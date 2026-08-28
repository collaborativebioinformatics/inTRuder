"""Compare candidate novel tandem repeats against the STRchive disease catalog.

One step of a file-in/file-out pipeline: it reads a table of candidate repeats
from the upstream filtering step and writes the same table with STRchive
annotation columns appended. It imports no other pipeline step -- only
:mod:`trcore`, for the motif and coordinate primitives every step must agree on.

    from intruder.pipeline.strchive.catalog import Catalog
    from intruder.pipeline.strchive.compare import Query, compare

    catalog = Catalog.load()                       # downloads + caches on first use
    match = compare(Query.from_point("chr1", 94418430, "CCG", rep_units=120), catalog)
    match.status                                   # 'pathogenic_expansion'
"""

from .catalog import (
    CACHE_ENV,
    STRCHIVE_VERSION,
    Catalog,
    DiseaseLocus,
    default_cache,
    fetch,
)
from .compare import OUTPUT_COLUMNS, STATUSES, Match, Query, compare

__all__ = [
    "CACHE_ENV",
    "OUTPUT_COLUMNS",
    "STATUSES",
    "STRCHIVE_VERSION",
    "Catalog",
    "DiseaseLocus",
    "Match",
    "Query",
    "compare",
    "default_cache",
    "fetch",
]
