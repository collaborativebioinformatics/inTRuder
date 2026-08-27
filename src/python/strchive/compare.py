"""Score a candidate novel tandem repeat against the STRchive disease catalog.

Input is whatever the upstream filtering step emits: a genomic coordinate, the
motif called inside the insertion, and -- where available -- the gene it was
annotated to and how many copies of the motif the insertion carries.

Three questions are answered, in order, because each one only makes sense if
the previous one was answered yes:

    1. LOCUS   Does the insertion land on (or within ``window`` bp of) a known
               disease locus? 82 loci in ~3 Gb means the honest answer is
               almost always no, and that is a result, not a failure.

    2. MOTIF   Does the called motif match a motif STRchive records at that
               locus, and in which class -- pathogenic, reference, benign,
               unknown, interruption? A locus hit whose motif matches *nothing*
               is the motif-novelty case: a known disease locus carrying a unit
               nobody has catalogued there.

    3. ALLELE  Does the resulting copy number reach the pathogenic range?
               The insertion is called against the reference, so the copies it
               carries are *additional* to those already in the reference:

                   est_copies = ref_copies + rep_units

               This is an estimate. It assumes the insertion sits inside the
               reference repeat and extends it, rather than replacing it or
               landing beside it, and it inherits whatever error the caller's
               ``rep_units`` carries. Treat it as a triage signal.

WHY COORDINATES AND NOT GENE
----------------------------
Matching is driven by position. A novel locus may carry no gene annotation at
all, and gene symbols disagree between annotation sources, so gene is reported
as an independent agreement check (``gene_agrees``) rather than used as the key.
"""

from __future__ import annotations

from dataclasses import dataclass

from trcore.coords import normalize_chrom, to_internal
from trcore.motifs import canonical_motif, motif_distance

from .catalog import MOTIF_CLASSES, Catalog, DiseaseLocus, equivalence_for

#: Rollup verdicts, most to least interesting.
STATUSES = (
    "pathogenic_expansion",   # disease locus + pathogenic motif + pathogenic copy number
    "pathogenic_motif",       # disease locus + pathogenic motif, copies below range
    "locus_novel_motif",      # disease locus, motif not catalogued there
    "locus_known_motif",      # disease locus + reference/benign/unknown motif
    "no_locus_match",         # no disease locus within the window
)


@dataclass(frozen=True)
class Query:
    """One candidate repeat to screen.

    ``start``/``end`` are 0-based half-open. Insertions are a single reference
    coordinate rather than an interval, so ``from_point`` converts a VCF-style
    1-based position into the one-base interval this expects.
    """

    chrom: str
    start: int
    end: int
    motif: str
    gene: str | None = None
    rep_units: float | None = None
    label: str = ""

    @classmethod
    def from_point(cls, chrom: str, pos: int, motif: str, *, coord_base: int = 1,
                   gene: str | None = None, rep_units: float | None = None,
                   label: str = "") -> Query:
        """Build a query from an insertion point in ``coord_base`` coordinates."""
        start = to_internal(pos, coord_base)
        return cls(chrom=normalize_chrom(chrom), start=start, end=start + 1,
                   motif=motif, gene=gene, rep_units=rep_units, label=label)


@dataclass(frozen=True)
class Match:
    """Result of screening one query against the catalog."""

    query: Query
    status: str
    locus: DiseaseLocus | None = None
    distance: int | None = None          # bp to the locus; 0 when overlapping
    n_nearby: int = 0                    # disease loci within the window
    motif_class: str = "none"            # pathogenic | reference | benign | ...
    motif_edits: int | None = None       # 0 when the motifs are equivalent
    matched_motif: str = ""              # the STRchive motif that matched
    est_copies: float | None = None
    allele_class: str = "unknown"

    @property
    def is_hit(self) -> bool:
        """True when the query landed on a catalogued disease locus."""
        return self.locus is not None

    @property
    def gene_agrees(self) -> bool | None:
        """Whether the upstream gene annotation agrees with STRchive's.

        ``None`` when either side has no gene to compare.
        """
        if self.locus is None or not self.query.gene:
            return None
        return self.query.gene.strip().upper() == self.locus.gene.strip().upper()


def classify_motif(motif: str, locus: DiseaseLocus, *, max_edits: int = 0,
                   stranded: bool = False) -> tuple[str, int | None, str]:
    """Find the best class for ``motif`` among the motifs STRchive lists at ``locus``.

    Classes are tried in ``MOTIF_CLASSES`` order, so an exact pathogenic match
    wins over an exact reference match when a locus lists the motif as both.
    Within a class the smallest edit distance wins. Returns
    ``("none", None, "")`` when nothing matches within ``max_edits``.
    """
    equivalence = equivalence_for(stranded)
    query_key = canonical_motif(motif, equivalence)
    if not query_key:
        return "none", None, ""

    best: tuple[str, int, str] | None = None
    for cls in MOTIF_CLASSES:
        for raw in locus.motifs.get(cls, ()):
            dist = motif_distance(motif, raw, max_edits, equivalence)
            if dist > max_edits:
                continue
            if best is None or dist < best[1]:
                best = (cls, dist, raw)
            if dist == 0:
                break
        if best is not None and best[1] == 0:
            break
    return best if best is not None else ("none", None, "")


def _rank(candidate: tuple[str, int | None, str], distance: int) -> tuple:
    """Sort key for choosing among nearby loci: motif match first, then proximity.

    A pathogenic motif match a few hundred bp away is a more useful report than
    a motif-less overlap, so the motif class outranks the distance.
    """
    cls, edits, _ = candidate
    cls_rank = MOTIF_CLASSES.index(cls) if cls in MOTIF_CLASSES else len(MOTIF_CLASSES)
    return (cls_rank, edits if edits is not None else 1 << 30, distance)


def compare(query: Query, catalog: Catalog, *, window: int = 0, max_motif_edits: int = 0,
            stranded: bool = False) -> Match:
    """Screen one query against the catalog and return a single verdict."""
    nearby = catalog.nearby(query.chrom, query.start, query.end, window=window)
    if not nearby:
        return Match(query=query, status="no_locus_match")

    scored = []
    for locus in nearby:
        distance = locus.distance_to(query.start, query.end)
        candidate = classify_motif(query.motif, locus, max_edits=max_motif_edits,
                                   stranded=stranded)
        scored.append((_rank(candidate, distance), distance, candidate, locus))
    scored.sort(key=lambda item: item[0])
    _, distance, (motif_class, motif_edits, matched_motif), locus = scored[0]

    est_copies = None
    if query.rep_units is not None and locus.ref_copies is not None:
        est_copies = locus.ref_copies + query.rep_units
    allele_class = locus.allele_class(est_copies)

    if motif_class == "none":
        status = "locus_novel_motif"
    elif motif_class == "pathogenic":
        status = "pathogenic_expansion" if allele_class == "pathogenic" else "pathogenic_motif"
    else:
        status = "locus_known_motif"

    return Match(
        query=query,
        status=status,
        locus=locus,
        distance=distance,
        n_nearby=len(nearby),
        motif_class=motif_class,
        motif_edits=motif_edits,
        matched_motif=matched_motif,
        est_copies=est_copies,
        allele_class=allele_class,
    )


#: Columns appended to each input row by ``annotate``.
OUTPUT_COLUMNS = (
    "strchive_status",
    "strchive_id",
    "strchive_gene",
    "strchive_disease",
    "strchive_inheritance",
    "strchive_evidence",
    "strchive_distance_bp",
    "strchive_n_nearby",
    "strchive_motif_class",
    "strchive_motif_edits",
    "strchive_matched_motif",
    "strchive_ref_copies",
    "strchive_est_copies",
    "strchive_allele_class",
    "strchive_pathogenic_min",
    "strchive_pathogenic_max",
    "strchive_novel_in_ref",
    "strchive_gene_agrees",
    "strchive_catalog",
)


def _blank(value) -> str:
    return "" if value is None else str(value)


def as_row(match: Match, catalog: Catalog) -> dict[str, str]:
    """Flatten a ``Match`` into the ``OUTPUT_COLUMNS`` fields."""
    locus = match.locus
    stamp = f"STRchive {catalog.version} ({catalog.build})"
    if locus is None:
        row = dict.fromkeys(OUTPUT_COLUMNS, "")
        row["strchive_status"] = match.status
        row["strchive_n_nearby"] = "0"
        row["strchive_motif_class"] = "none"
        row["strchive_allele_class"] = "unknown"
        row["strchive_catalog"] = stamp
        return row

    agrees = match.gene_agrees
    return {
        "strchive_status": match.status,
        "strchive_id": locus.id,
        "strchive_gene": locus.gene,
        "strchive_disease": locus.disease,
        "strchive_inheritance": ",".join(locus.inheritance),
        "strchive_evidence": ",".join(locus.evidence),
        "strchive_distance_bp": _blank(match.distance),
        "strchive_n_nearby": str(match.n_nearby),
        "strchive_motif_class": match.motif_class,
        "strchive_motif_edits": _blank(match.motif_edits),
        "strchive_matched_motif": match.matched_motif,
        "strchive_ref_copies": _blank(locus.ref_copies),
        "strchive_est_copies": "" if match.est_copies is None else f"{match.est_copies:g}",
        "strchive_allele_class": match.allele_class,
        "strchive_pathogenic_min": _blank(locus.pathogenic_min),
        "strchive_pathogenic_max": _blank(locus.pathogenic_max),
        "strchive_novel_in_ref": _blank(locus.novel),
        "strchive_gene_agrees": "" if agrees is None else str(agrees).lower(),
        "strchive_catalog": stamp,
    }
