"""FastAPI application: data API for the visualization, SSE endpoint for the agent."""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent import sse, stream_agent
from app.agent.llm import describe_provider
from app.config import settings
from app.util.registry import registry

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry.load()
    available = registry.available_datasets()
    logger.info(
        "registry ready: %d/%d datasets available", len(available), len(registry.datasets)
    )
    if not settings.agent_enabled:
        logger.warning(
            "no credential for LLM_PROVIDER=%s — the data API works, chat will "
            "return a configuration error. See backend/.env.example",
            settings.llm_provider,
        )
    yield


app = FastAPI(title="novelTRs API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Meta
# --------------------------------------------------------------------------- #

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "datasets": {
            "available": [d.name for d in registry.available_datasets()],
            "unavailable": [
                {"name": d.name, "error": d.error}
                for d in registry.datasets.values()
                if not d.available
            ],
        },
        "llm": describe_provider(settings.llm_provider),
        "agent_enabled": settings.agent_enabled,
    }


@app.get("/api/datasets")
def datasets() -> dict[str, Any]:
    return {"datasets": [d.detail() for d in registry.datasets.values()]}


# --------------------------------------------------------------------------- #
# Visualization data
# --------------------------------------------------------------------------- #

def _available(name: str) -> bool:
    return name in {d.name for d in registry.available_datasets()}


def _rows(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    """Run a query and return dict rows. Uses a private cursor — see registry."""
    cursor = registry.cursor().execute(sql, params or [])
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _require_loci() -> None:
    if not _available("demo_loci"):
        raise HTTPException(
            status_code=503,
            detail="The 'demo_loci' dataset is not available. Run: "
                   "cd backend && uv run python scripts/make_demo_data.py",
        )


# --------------------------------------------------------------------------- #
# Genomic ranges
# --------------------------------------------------------------------------- #

#: A range as a person writes it: `chr3:1,000-50,000`. The `chr` prefix is
#: optional because VCF and Ensembl drop it, thousands separators are tolerated
#: because they survive a copy-paste out of a genome browser, and `..` is
#: accepted beside `-` for the same reason.
_REGION = re.compile(
    r"^(?:chr)?(\d{1,2}|X|Y|M|MT)\s*:\s*([\d,_]+)\s*(?:\.\.|-)\s*([\d,_]+)$",
    re.IGNORECASE,
)


def _normalize_chrom(name: str) -> str:
    """`3` -> `chr3`, `x` -> `chrX`, `MT` -> `chrM`."""
    upper = name.upper()
    return "chr" + ("M" if upper == "MT" else upper)


def parse_region(region: str) -> tuple[str, int, int]:
    """`chr3:1,000-50,000` -> `("chr3", 1000, 50000)`.

    Both ends are inclusive, which is how a range reads in a genome browser
    rather than how a BED file stores one — this string is typed by a person, not
    parsed out of a file. A backwards range is read in the order it was meant
    rather than matching nothing.
    """
    match = _REGION.match(region.strip())
    if match is None:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot read {region!r} as a genomic range. Write it like "
                   "'chr3:1000-50000'.",
        )
    name, start_text, end_text = match.groups()
    start = int(start_text.replace(",", "").replace("_", ""))
    end = int(end_text.replace(",", "").replace("_", ""))
    return _normalize_chrom(name), min(start, end), max(start, end)


#: Filters that depend on a column the current table may not carry. Each maps to
#: the column that supplies it; when that column is absent the filter is reported
#: back as ignored rather than silently matching everything. `demo_loci` carries
#: the reference-screen columns, so today only `sample` (it is one row per locus,
#: not per call) and `strchive_status` actually land here.
_SCREENED_ONLY = {
    "novelty": "novelty",
    "platform_agreement": "ucsc_novelty",
    "min_insertion_purity": "insertion_purity",
    "sample": "sample",
    "strchive_status": "strchive_status",
}


def _columns(table: str) -> set[str]:
    dataset = registry.datasets.get(table)
    return set(dataset.columns) if dataset and dataset.available else set()


def _agreement_clause(mode: str) -> str:
    """Where the two catalogs stand relative to each other.

    'both' means both call it novel — the case worth trusting, because UCSC and
    TRExplorer were compiled separately.
    """
    novel = "{col} <> 'known'"
    if mode == "both":
        return f"({novel.format(col='ucsc_novelty')} AND {novel.format(col='trexplorer_novelty')})"
    if mode == "ucsc_only":
        return f"({novel.format(col='ucsc_novelty')} AND trexplorer_novelty = 'known')"
    if mode == "trexplorer_only":
        return f"(ucsc_novelty = 'known' AND {novel.format(col='trexplorer_novelty')})"
    return "(ucsc_novelty = 'known' AND trexplorer_novelty = 'known')"


def _filter_clause(
    novel_only: bool,
    chrom: str | None,
    motif_class: str | None,
    min_motif_len: int | None,
    min_samples: int | None,
    min_purity: float | None,
    disease_gene_only: bool,
    gene: str | None,
    region: str | None = None,
    gene_query: str | None = None,
    novelty: str | None = None,
    platform_agreement: str | None = None,
    min_insertion_purity: float | None = None,
    sample: str | None = None,
    strchive_status: str | None = None,
    available: set[str] | None = None,
) -> tuple[str, list[Any], list[str]]:
    """Build the WHERE clause, and report which filters the table cannot honour."""
    available = available if available is not None else set()
    clauses: list[str] = []
    params: list[Any] = []
    ignored: list[str] = []

    def needs(name: str) -> bool:
        """True when this filter can actually run against the current table."""
        column = _SCREENED_ONLY[name]
        if column in available:
            return True
        ignored.append(name)
        return False

    if novel_only:
        clauses.append("novel")
    if chrom:
        clauses.append("chrom = ?")
        params.append(chrom)
    if motif_class:
        clauses.append("motif_class = ?")
        params.append(motif_class)
    if min_motif_len is not None:
        clauses.append("motif_len >= ?")
        params.append(min_motif_len)
    if min_samples is not None:
        clauses.append("n_samples >= ?")
        params.append(min_samples)
    if min_purity is not None:
        clauses.append("mean_purity >= ?")
        params.append(min_purity)
    if disease_gene_only:
        clauses.append("disease_gene")
    if gene:
        clauses.append("gene = ?")
        params.append(gene)
    if region:
        # A candidate locus is an insertion *point*, so overlapping a range means
        # the insertion site falls inside it. Both ends inclusive; see parse_region.
        region_chrom, start, end = parse_region(region)
        clauses.append("(chrom = ? AND pos BETWEEN ? AND ?)")
        params.extend([region_chrom, start, end])
    if gene_query:
        # `contains` rather than LIKE: this text comes from a search box, where
        # % and _ mean those characters and not wildcards.
        clauses.append("contains(upper(gene), upper(?))")
        params.append(gene_query)

    if novelty and needs("novelty"):
        clauses.append("novelty = ?")
        params.append(novelty)
    if platform_agreement and needs("platform_agreement"):
        clauses.append(_agreement_clause(platform_agreement))
    if min_insertion_purity is not None and needs("min_insertion_purity"):
        clauses.append("insertion_purity >= ?")
        params.append(min_insertion_purity)
    if sample and needs("sample"):
        clauses.append("sample = ?")
        params.append(sample)
    if strchive_status and needs("strchive_status"):
        clauses.append("strchive_status = ?")
        params.append(strchive_status)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params, ignored


# Chromosomes sort as strings otherwise, which puts chr10 before chr2.
_CHROM_ORDER = (
    "CASE WHEN chrom = 'chrX' THEN 23 WHEN chrom = 'chrY' THEN 24 "
    "ELSE TRY_CAST(replace(chrom, 'chr', '') AS INTEGER) END"
)

#: Sort keys, as the columns each orders by and the direction it means when
#: nobody says otherwise. "Biggest" is what someone asking for size wants;
#: "first on the chromosome" is what they want from position. Every sort but
#: position falls back to genomic order, so ties never reshuffle between two
#: requests for the same page.
_SORTS: dict[str, tuple[tuple[str, ...], str]] = {
    # Genomic order is the domain-native default, and it interleaves novel and
    # catalogued loci so the novel fraction reads as texture down the list.
    "position": ((_CHROM_ORDER, "pos"), "ASC"),
    "novel": (("novel", "motif_len"), "DESC"),
    "size": (("median_len",), "DESC"),
    "support": (("n_samples",), "DESC"),
    "motif_len": (("motif_len",), "DESC"),
    "purity": (("mean_purity",), "DESC"),
    # How many separate repeat arrays the drawn allele is built from — a
    # compound locus is several tandem repeats inside one insertion. Computed
    # from demo_segments rather than read off a column; see `_order_by`.
    "arrays": (("n_arrays",), "DESC"),
}

#: Sorts whose column comes from the per-allele table, not from the locus row.
_SEGMENT_SORTS = frozenset({"arrays"})


def _order_by(sort: str, sort_dir: str | None) -> str:
    """ORDER BY for one sort key, in the requested or its natural direction."""
    columns, natural = _SORTS[sort]
    direction = (sort_dir or natural).upper()
    clause = ", ".join(f"{column} {direction} NULLS LAST" for column in columns)
    if sort == "position":
        return clause
    return f"{clause}, {_CHROM_ORDER} ASC, pos ASC"


#: The allele the catalog draws for a locus: the median-length carrier.
#:
#: Shared by the strip query and the `arrays` sort, so the number the list is
#: ordered by is the number of blocks you can count on the row — sorting by
#: something the row does not show would be a control with no visible effect.
#: `{where}` narrows the scan to the page being returned; the sort cannot use
#: it, because the ordering is what decides which loci that page holds.
_REPRESENTATIVE_ALLELE = """
    allele AS (
        SELECT locus_id, sample, max("end") AS allele_len
        FROM demo_segments {where}
        GROUP BY 1, 2
    ),
    ranked AS (
        -- `sample` breaks ties. Carriers routinely share an allele length, and
        -- without a total order row_number() is free to pick a different one of
        -- them per query — which would let the strip a row draws disagree with
        -- the array count that row is sorted by, and change between requests.
        SELECT locus_id, sample,
               row_number() OVER (
                   PARTITION BY locus_id ORDER BY allele_len, sample
               ) AS rn,
               count(*) OVER (PARTITION BY locus_id) AS n
        FROM allele
    ),
    representative AS (
        -- Integer division: DuckDB's `/` is float, so an even carrier count
        -- would match no row at all.
        SELECT locus_id, sample FROM ranked WHERE rn = (n + 1) // 2
    )
"""

_ARRAY_COUNTS = f"""WITH {_REPRESENTATIVE_ALLELE.format(where="")},
    arrays AS (
        SELECT r.locus_id,
               count(*) FILTER (WHERE s.seg_type = 'repeat') AS n_arrays
        FROM representative r
        JOIN demo_segments s
          ON s.locus_id = r.locus_id AND s.sample = r.sample
        GROUP BY 1
    )
"""


@app.get("/api/loci")
def loci(
    novel_only: bool = False,
    chrom: str | None = None,
    motif_class: str | None = None,
    min_motif_len: int | None = None,
    min_samples: int | None = None,
    min_purity: float | None = None,
    disease_gene_only: bool = False,
    gene: str | None = None,
    region: str | None = None,
    gene_query: str | None = None,
    novelty: str | None = Query(None, pattern="^(known|novel_motif|novel_locus)$"),
    platform_agreement: str | None = Query(
        None, pattern="^(both|ucsc_only|trexplorer_only|neither)$"
    ),
    min_insertion_purity: float | None = None,
    sample: str | None = None,
    strchive_status: str | None = None,
    limit: int = Query(300, le=2000),
    offset: int = 0,
    include_strips: bool = False,
    sort: str = Query(
        "position",
        pattern="^(position|novel|size|support|arrays|motif_len|purity)$",
    ),
    sort_dir: str | None = Query(None, pattern="^(asc|desc)$"),
) -> dict[str, Any]:
    """Filtered locus list backing the catalog view.

    `region` takes a genomic range as a person writes it — `chr3:1,000-50,000`,
    with or without the `chr` and the commas — and keeps the loci whose insertion
    site falls inside it. A range that does not parse is a 400 rather than an
    empty list, because an empty list reads as a finding. `gene_query` is the
    free-text counterpart of `gene`: a case-insensitive substring of the gene
    symbol, for a search box rather than an exact pick.

    With `include_strips`, also returns the segment structure of one
    representative (median-length) allele per locus, so the catalog can render
    real motif barcodes rather than summary bars.

    Filters needing a column the current table lacks come back in
    `ignored_filters` instead of being dropped on the floor — a control that
    silently matches everything reads as a result, which is worse than an error.
    The same honesty applies to `sort`: the key actually used comes back in
    `sort`, so a sort that needs a table this deployment has not registered
    reports the order the list is really in rather than the one that was asked
    for.
    """
    _require_loci()
    where, params, ignored = _filter_clause(
        novel_only, chrom, motif_class, min_motif_len,
        min_samples, min_purity, disease_gene_only, gene,
        region, gene_query,
        novelty, platform_agreement, min_insertion_purity, sample, strchive_status,
        available=_columns("demo_loci"),
    )

    needs_segments = sort in _SEGMENT_SORTS
    if needs_segments and not _available("demo_segments"):
        sort = "position"
        needs_segments = False
    prefix = _ARRAY_COUNTS if needs_segments else ""
    source = (
        "demo_loci l LEFT JOIN arrays a ON a.locus_id = l.locus_id"
        if needs_segments
        else "demo_loci l"
    )

    con = registry.cursor()
    total = con.execute(f"SELECT count(*) FROM demo_loci {where}", params).fetchone()[0]
    cursor = con.execute(
        f"""{prefix}
            SELECT l.* FROM {source} {where}
            ORDER BY {_order_by(sort, sort_dir)}
            LIMIT ? OFFSET ?""",
        [*params, limit, offset],
    )
    columns = [d[0] for d in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    strips: dict[str, list[dict[str, Any]]] = {}
    if include_strips and rows and _available("demo_segments"):
        locus_ids = [r["locus_id"] for r in rows]
        placeholders = ",".join("?" for _ in locus_ids)
        strip_cursor = con.execute(
            f"""WITH {_REPRESENTATIVE_ALLELE.format(
                    where=f"WHERE locus_id IN ({placeholders})"
                )}
                SELECT s.locus_id, s.sample, s.seg_index, s.seg_type,
                       s.start, s."end", s.motif, s.purity, s.units
                FROM demo_segments s
                JOIN representative r ON r.locus_id = s.locus_id AND r.sample = s.sample
                ORDER BY s.locus_id, s.seg_index""",
            locus_ids,
        )
        strip_columns = [d[0] for d in strip_cursor.description]
        for record in strip_cursor.fetchall():
            segment = dict(zip(strip_columns, record))
            strips.setdefault(segment["locus_id"], []).append(segment)

    return {
        "total": total,
        "returned": len(rows),
        "offset": offset,
        "loci": rows,
        "strips": strips,
        "ignored_filters": ignored,
        "sort": sort,
        "sort_dir": (sort_dir or _SORTS[sort][1]).lower(),
    }


@app.get("/api/loci/{locus_id}")
def locus_detail(locus_id: str) -> dict[str, Any]:
    """One locus plus every carrier's segment structure — this drives the barcode."""
    _require_loci()
    con = registry.cursor()
    cursor = con.execute("SELECT * FROM demo_loci WHERE locus_id = ?", [locus_id])
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No locus {locus_id!r}")
    locus = dict(zip([d[0] for d in cursor.description], row))

    segments: list[dict[str, Any]] = []
    if _available("demo_segments"):
        seg_cursor = con.execute(
            """SELECT sample, seg_index, seg_type, start, "end", motif, purity, units
               FROM demo_segments WHERE locus_id = ?
               ORDER BY sample, seg_index""",
            [locus_id],
        )
        seg_columns = [d[0] for d in seg_cursor.description]
        segments = [dict(zip(seg_columns, r)) for r in seg_cursor.fetchall()]

    by_sample: dict[str, dict[str, Any]] = {}
    for segment in segments:
        entry = by_sample.setdefault(
            segment["sample"], {"sample": segment["sample"], "segments": [], "allele_len": 0}
        )
        entry["segments"].append(segment)
        entry["allele_len"] = max(entry["allele_len"], segment["end"])

    alleles = sorted(by_sample.values(), key=lambda a: a["allele_len"], reverse=True)
    return {"locus": locus, "alleles": alleles}


@app.get("/api/summary")
def summary() -> dict[str, Any]:
    """Cohort funnel plus the breakdowns the landing page renders."""
    _require_loci()
    con = registry.cursor()

    total, non_homopolymer, confident, novel, novel_disease = con.execute(
        """SELECT
             count(*),
             count(*) FILTER (WHERE motif_class <> 'homopolymer'),
             count(*) FILTER (WHERE motif_class <> 'homopolymer' AND mean_purity >= 0.8),
             count(*) FILTER (WHERE motif_class <> 'homopolymer' AND mean_purity >= 0.8 AND novel),
             count(*) FILTER (WHERE motif_class <> 'homopolymer' AND mean_purity >= 0.8
                              AND novel AND disease_gene)
           FROM demo_loci"""
    ).fetchone()

    def rows(sql: str) -> list[dict[str, Any]]:
        cursor = con.execute(sql)
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, r)) for r in cursor.fetchall()]

    return {
        "funnel": [
            {"stage": "Candidate insertion loci", "count": total,
             "note": "Merged INS calls carrying a detected repeat"},
            {"stage": "Non-homopolymer", "count": non_homopolymer,
             "note": "Drop 1bp motifs"},
            {"stage": "Confident repeats", "count": confident,
             "note": "Mean purity ≥ 0.80"},
            {"stage": "Absent from all catalogs", "count": novel,
             "note": "No equivalent motif in UCSC simpleRepeat or TRExplorer"},
            {"stage": "In a disease gene", "count": novel_disease,
             "note": "Novel and overlapping a known repeat-expansion gene"},
        ],
        "by_class": rows(
            """SELECT motif_class,
                      count(*) AS n,
                      count(*) FILTER (WHERE novel) AS novel
               FROM demo_loci GROUP BY 1 ORDER BY n DESC"""
        ),
        "by_chrom": rows(
            f"""SELECT chrom,
                       count(*) AS n,
                       count(*) FILTER (WHERE novel) AS novel
                FROM demo_loci GROUP BY 1
                ORDER BY {_CHROM_ORDER}"""
        ),
        "synthetic": any(d.synthetic for d in registry.available_datasets()),
    }


# --------------------------------------------------------------------------- #
# STRchive — the disease-locus reference, and our candidates screened against it
# --------------------------------------------------------------------------- #

def _require_strchive() -> None:
    if not _available("strchive_loci"):
        raise HTTPException(
            status_code=503,
            detail="The 'strchive_loci' dataset is not available. Run: "
                   "cd backend && uv run python scripts/fetch_strchive.py",
        )


@app.get("/api/strchive/summary")
def strchive_summary() -> dict[str, Any]:
    """Catalog-level counts, plus how our own callset scored against it.

    The `screen` block is null until the pipeline's STRchive step has been run —
    the page is built to render the catalog alone until then.
    """
    _require_strchive()

    totals = _rows(
        """SELECT count(*) AS n_loci,
                  count(*) FILTER (WHERE novel_in_reference) AS n_novel_in_reference,
                  count(*) FILTER (WHERE pathogenic_min IS NOT NULL) AS n_with_range,
                  count(*) FILTER (WHERE ref_copies IS NULL) AS n_without_ref_copies,
                  max(catalog_version) AS catalog_version
           FROM strchive_loci"""
    )[0]

    # Evidence is single-valued in practice; inheritance genuinely is not (AD;AR),
    # so it gets split rather than grouped as a string.
    by_evidence = _rows(
        """SELECT evidence,
                  count(*) AS n,
                  count(*) FILTER (WHERE novel_in_reference) AS novel
           FROM strchive_loci GROUP BY 1 ORDER BY n DESC"""
    )
    by_inheritance = _rows(
        """SELECT trim(part) AS inheritance, count(*) AS n
           FROM strchive_loci, unnest(string_split(inheritance, ';')) AS t(part)
           WHERE trim(part) <> '' GROUP BY 1 ORDER BY n DESC"""
    )

    screen: dict[str, Any] | None = None
    if _available("strchive_calls"):
        counts = _rows(
            """SELECT strchive_status AS status,
                      count(*) AS rows,
                      count(DISTINCT chrom || ':' || ins_coord) AS loci
               FROM strchive_calls GROUP BY 1 ORDER BY rows DESC"""
        )
        spread = _rows(
            """SELECT count(*) AS n_rows,
                      count(DISTINCT chrom || ':' || ins_coord) AS n_loci,
                      min(TRY_CAST(strchive_distance_bp AS BIGINT))
                        FILTER (WHERE strchive_id IS NOT NULL AND strchive_id <> '')
                        AS nearest_hit_bp
               FROM strchive_calls"""
        )[0]
        screen = {"available": True, "by_status": counts, **spread}

    return {**totals, "by_evidence": by_evidence, "by_inheritance": by_inheritance,
            "screen": screen}


@app.get("/api/strchive/loci")
def strchive_loci(
    novel_in_reference: bool = False,
    evidence: str | None = None,
    inheritance: str | None = None,
    gene: str | None = None,
    q: str | None = None,
    limit: int = Query(200, le=500),
) -> dict[str, Any]:
    """The disease-locus catalog, filtered. Reference knowledge, not our results."""
    _require_strchive()
    clauses: list[str] = []
    params: list[Any] = []
    if novel_in_reference:
        clauses.append("novel_in_reference")
    if evidence:
        clauses.append("evidence = ?")
        params.append(evidence)
    if inheritance:
        clauses.append("inheritance LIKE ?")
        params.append(f"%{inheritance}%")
    if gene:
        clauses.append("upper(gene) = upper(?)")
        params.append(gene)
    if q:
        clauses.append(
            "(upper(gene) LIKE upper(?) OR upper(disease) LIKE upper(?) "
            "OR upper(id) LIKE upper(?))"
        )
        params.extend([f"%{q}%"] * 3)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    total = registry.cursor().execute(
        f"SELECT count(*) FROM strchive_loci {where}", params
    ).fetchone()[0]
    # Novel-in-reference first: on this project's page those are the loci the
    # argument is about, and burying them in genomic order hides the point.
    loci = _rows(
        f"""SELECT * FROM strchive_loci {where}
            ORDER BY novel_in_reference DESC, gene
            LIMIT ?""",
        [*params, limit],
    )
    return {"total": total, "returned": len(loci), "loci": loci}


@app.get("/api/strchive/matches")
def strchive_matches(
    status: str | None = None,
    limit: int = Query(200, le=500),
) -> dict[str, Any]:
    """Our candidate repeats that landed on a known disease locus.

    Returns `available: false` rather than 503 when the screened table is not
    registered — an interface that has not been run yet is a different thing from
    one that is broken, and the page says so.
    """
    if not _available("strchive_calls"):
        return {
            "available": False,
            "note": "No screened callset registered. Run the novelty screen and "
                    "`strchive annotate`, then point data/web/strchive-calls.yaml "
                    "at the output.",
            "total": 0,
            "matches": [],
        }

    clauses = ["strchive_id IS NOT NULL", "strchive_id <> ''"]
    params: list[Any] = []
    if status:
        clauses.append("strchive_status = ?")
        params.append(status)
    where = "WHERE " + " AND ".join(clauses)

    total = registry.cursor().execute(
        f"SELECT count(*) FROM strchive_calls {where}", params
    ).fetchone()[0]
    matches = _rows(
        f"""SELECT chrom, ins_coord, SVID, sample, motif, canonical_motif,
                   rep_units, purity, insertion_purity, novelty,
                   ucsc_novelty, trexplorer_novelty,
                   strchive_status, strchive_id, strchive_gene, strchive_disease,
                   strchive_inheritance, strchive_evidence, strchive_distance_bp,
                   strchive_motif_class, strchive_motif_edits, strchive_matched_motif,
                   strchive_ref_copies, strchive_est_copies, strchive_allele_class,
                   strchive_pathogenic_min, strchive_pathogenic_max,
                   strchive_novel_in_ref, strchive_catalog
            FROM strchive_calls {where}
            -- Most interesting first: a pathogenic expansion outranks a bare
            -- locus hit, and closer outranks further within a status.
            ORDER BY CASE strchive_status
                       WHEN 'pathogenic_expansion' THEN 0
                       WHEN 'pathogenic_motif' THEN 1
                       WHEN 'locus_novel_motif' THEN 2
                       WHEN 'locus_known_motif' THEN 3
                       ELSE 4 END,
                     TRY_CAST(strchive_distance_bp AS BIGINT)
            LIMIT ?""",
        [*params, limit],
    )
    return {"available": True, "note": "", "total": total, "matches": matches}


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #

class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


@app.post("/api/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """Stream one agent turn as server-sent events. Event shapes: see app/agent.py."""
    payload = [m.model_dump() for m in request.messages]

    async def event_stream():
        async for event in stream_agent(payload):
            yield sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
