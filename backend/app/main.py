"""FastAPI application: data API for the visualization, SSE endpoint for the agent."""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.datastructures import Headers

from app import switches, uploads
from app.agent import sse, stream_agent
from app.config import settings
from app.llm import describe_provider
from app.registry import ROLES, registry

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


class SwitchesMiddleware:
    """Carry the caller's dataset switches for the length of one request.

    Pure ASGI rather than `@app.middleware("http")`: that decorator's
    BaseHTTPMiddleware runs the endpoint in a child task and streams the response
    body after returning, so a context variable set there would already be gone
    by the time the agent's tools ran on the SSE path. This runs in the same task
    as everything it wraps.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        header = Headers(scope=scope).get(switches.HEADER)
        token = switches.bind(switches.parse(header))
        try:
            await self.app(scope, receive, send)
        finally:
            switches.reset(token)


app.add_middleware(SwitchesMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    # Includes switches.HEADER, which is a custom header and so is preflighted.
    allow_headers=["*"],
)


def _off() -> frozenset[str]:
    """The datasets this caller does not want read, defaults applied.

    Every handler that resolves a table goes through here, so a switch reaches
    the whole API — the surfaces, the funnel, and the assistant — without any of
    them knowing where the value came from.
    """
    return registry.switched_off(switches.current())


# --------------------------------------------------------------------------- #
# Meta
# --------------------------------------------------------------------------- #

@app.get("/api/health")
def health() -> dict[str, Any]:
    off = _off()
    return {
        "status": "ok",
        "datasets": {
            "available": [d.name for d in registry.available_datasets(off)],
            # A switched-off dataset is not reported here: it is not *missing*,
            # and putting it beside a manifest whose file never arrived would
            # give it an empty reason where the others have a real one.
            "unavailable": [
                {"name": d.name, "error": d.error}
                for d in registry.datasets.values()
                if not d.available and d.name not in off
            ],
            "disabled": sorted(off),
        },
        "llm": describe_provider(settings.llm_provider),
        "agent_enabled": settings.agent_enabled,
    }


@app.get("/api/datasets")
def datasets() -> dict[str, Any]:
    """Every registered dataset, with where its switch starts and where it is.

    `default_enabled` is the server's — it depends on what data exists here.
    `enabled` folds in the caller's own switches, so this is the one place the
    interface has to look to draw the row and the switch together.
    """
    off = _off()
    return {
        "datasets": [
            {**d.detail(), "enabled": d.name not in off}
            for d in registry.datasets.values()
        ],
        "roles": {role: registry.table_for(role, off) for role in ROLES},
    }


# --------------------------------------------------------------------------- #
# Visualization data
# --------------------------------------------------------------------------- #

def _available(name: str) -> bool:
    return name in {d.name for d in registry.available_datasets(_off())}


def _rows(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    """Run a query and return dict rows. Uses a private cursor — see registry."""
    cursor = registry.cursor().execute(sql, params or [])
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _loci_table() -> str:
    """The table the candidate-locus surface reads.

    Resolved by role rather than named, so registering an uploaded callset with
    `role: loci` repoints every query below it without a code change. Falls back
    to the committed demo fixture, which is what a fresh clone has — and skips
    whatever the caller has switched off, which is how one browser can look at
    the fixtures while another looks at the real cohort.
    """
    table = registry.table_for("loci", _off())
    if table is None:
        raise HTTPException(
            status_code=503,
            detail="No candidate-locus dataset is available. Generate the demo "
                   "fixtures with `cd backend && uv run python "
                   "scripts/make_demo_data.py`, upload a locus table and "
                   "register it with role 'loci', or switch one back on from the "
                   "Datasets page.",
        )
    return table


def _segments_table() -> str | None:
    """The per-allele table, when one is registered. Optional everywhere."""
    return registry.table_for("segments", _off())


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
#: back as ignored rather than silently matching everything. The demo table carries
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
    # from the segments table rather than read off a column; see `_order_by`.
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
        SELECT locus_id, sample, {allele} AS allele, max("end") AS allele_len
        FROM {segments} {where}
        GROUP BY 1, 2, 3
    ),
    ranked AS (
        -- `sample` breaks ties. Carriers routinely share an allele length, and
        -- without a total order row_number() is free to pick a different one of
        -- them per query — which would let the strip a row draws disagree with
        -- the array count that row is sorted by, and change between requests.
        -- `allele` joins that tiebreak so a diploid carrier's two haplotypes
        -- stay separable from each other.
        SELECT locus_id, sample, allele,
               row_number() OVER (
                   PARTITION BY locus_id ORDER BY allele_len, sample, allele
               ) AS rn,
               count(*) OVER (PARTITION BY locus_id) AS n
        FROM allele
    ),
    representative AS (
        -- Integer division: DuckDB's `/` is float, so an even carrier count
        -- would match no row at all.
        SELECT locus_id, sample, allele FROM ranked WHERE rn = (n + 1) // 2
    )
"""


#: How to address one allele in a segments table.
#:
#: A carrier is not always one allele. In the real HPRC callset 4,110 (locus,
#: sample) pairs hold two or three co-located insertion records — a diploid
#: sample whose haplotypes differ in length — and folding those onto the sample
#: would concatenate two haplotypes into one strip and draw it as though it were
#: a compound repeat, which is a different biological claim.
#:
#: A table that carries an `allele` column is therefore keyed on (sample,
#: allele); one that does not is keyed on the sample with a constant, which is
#: what the demo fixtures and any one-allele-per-carrier upload need. Resolving
#: it per table rather than requiring the column keeps `SEGMENTS_REQUIRED` as it
#: was, so a segments table written before this existed still registers.
def _allele_key(segments: str, alias: str = "") -> str:
    """The expression addressing one allele, `alias`-qualified where needed.

    Qualification is for the queries that join the segments table to
    `representative`, where a bare `allele` is ambiguous. It applies only to the
    real column — qualifying the constant would produce `s.1`.
    """
    if "allele" not in _columns(segments):
        return "1"
    return f"{alias}.allele" if alias else "allele"


def _representative_allele(segments: str, where: str = "") -> str:
    return _REPRESENTATIVE_ALLELE.format(
        segments=segments, where=where, allele=_allele_key(segments)
    )


def _array_counts(segments: str) -> str:
    allele = _allele_key(segments, "s")
    return f"""WITH {_representative_allele(segments)},
    arrays AS (
        SELECT r.locus_id,
               count(*) FILTER (WHERE s.seg_type = 'repeat') AS n_arrays
        FROM representative r
        JOIN {segments} s
          ON s.locus_id = r.locus_id AND s.sample = r.sample
         AND {allele} = r.allele
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
    loci_table = _loci_table()
    segments_table = _segments_table()
    where, params, ignored = _filter_clause(
        novel_only, chrom, motif_class, min_motif_len,
        min_samples, min_purity, disease_gene_only, gene,
        region, gene_query,
        novelty, platform_agreement, min_insertion_purity, sample, strchive_status,
        available=_columns(loci_table),
    )

    needs_segments = sort in _SEGMENT_SORTS and segments_table is not None
    if sort in _SEGMENT_SORTS and not needs_segments:
        sort = "position"
    prefix = _array_counts(segments_table) if needs_segments else ""
    source = (
        f"{loci_table} l LEFT JOIN arrays a ON a.locus_id = l.locus_id"
        if needs_segments
        else f"{loci_table} l"
    )

    con = registry.cursor()
    total = con.execute(f"SELECT count(*) FROM {loci_table} {where}", params).fetchone()[0]
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
    if include_strips and rows and segments_table:
        locus_ids = [r["locus_id"] for r in rows]
        placeholders = ",".join("?" for _ in locus_ids)
        strip_cursor = con.execute(
            f"""WITH {_representative_allele(
                    segments_table, f"WHERE locus_id IN ({placeholders})"
                )}
                SELECT s.locus_id, s.sample, s.seg_index, s.seg_type,
                       s.start, s."end", s.motif, s.purity, s.units
                FROM {segments_table} s
                JOIN representative r
                  ON r.locus_id = s.locus_id AND r.sample = s.sample
                 AND {_allele_key(segments_table, "s")} = r.allele
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
    loci_table = _loci_table()
    segments_table = _segments_table()
    con = registry.cursor()
    cursor = con.execute(f"SELECT * FROM {loci_table} WHERE locus_id = ?", [locus_id])
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No locus {locus_id!r}")
    locus = dict(zip([d[0] for d in cursor.description], row))

    segments: list[dict[str, Any]] = []
    if segments_table:
        seg_cursor = con.execute(
            f"""SELECT sample, {_allele_key(segments_table)} AS allele,
                       seg_index, seg_type, start, "end", motif, purity, units
                FROM {segments_table} WHERE locus_id = ?
                ORDER BY sample, allele, seg_index""",
            [locus_id],
        )
        seg_columns = [d[0] for d in seg_cursor.description]
        segments = [dict(zip(seg_columns, r)) for r in seg_cursor.fetchall()]

    # Keyed on (sample, allele), not sample: a diploid carrier of two co-located
    # insertions has two alleles here, and merging them would splice two
    # haplotypes into one strip. `sample` stays on each entry unchanged, so
    # highlighting a carrier still lights up both of its alleles.
    by_allele: dict[tuple[str, int], dict[str, Any]] = {}
    for segment in segments:
        key = (segment["sample"], segment["allele"])
        entry = by_allele.setdefault(
            key,
            {"sample": segment["sample"], "allele": segment["allele"],
             "segments": [], "allele_len": 0},
        )
        entry["segments"].append(segment)
        entry["allele_len"] = max(entry["allele_len"], segment["end"])

    alleles = sorted(by_allele.values(), key=lambda a: a["allele_len"], reverse=True)
    return {"locus": locus, "alleles": alleles}


@app.get("/api/summary")
def summary() -> dict[str, Any]:
    """Cohort funnel plus the breakdowns the landing page renders."""
    loci_table = _loci_table()
    segments_table = _segments_table()
    synthetic_tables = [
        table
        for table in (loci_table, segments_table)
        if table is not None and registry.datasets[table].synthetic
    ]
    con = registry.cursor()

    total, non_homopolymer, confident, novel, novel_disease = con.execute(
        f"""SELECT
             count(*),
             count(*) FILTER (WHERE motif_class <> 'homopolymer'),
             count(*) FILTER (WHERE motif_class <> 'homopolymer' AND mean_purity >= 0.8),
             count(*) FILTER (WHERE motif_class <> 'homopolymer' AND mean_purity >= 0.8 AND novel),
             count(*) FILTER (WHERE motif_class <> 'homopolymer' AND mean_purity >= 0.8
                              AND novel AND disease_gene)
           FROM {loci_table}"""
    ).fetchone()

    def rows(sql: str) -> list[dict[str, Any]]:
        cursor = con.execute(sql)
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, r)) for r in cursor.fetchall()]

    # How many genomes are behind these numbers. Sent rather than hardcoded in
    # the interface, because "3 / 68" printed over a 67-genome cohort is simply
    # wrong, and which cohort is loaded is exactly the thing a registered dataset
    # is allowed to change. Counted off the per-allele table where there is one,
    # since that is the only place every sample appears; otherwise the busiest
    # locus is the best lower bound available.
    cohort_size = con.execute(
        f"SELECT count(DISTINCT sample) FROM {segments_table}"
        if segments_table
        else f"SELECT max(n_samples) FROM {loci_table}"
    ).fetchone()[0]

    return {
        "cohort_size": cohort_size,
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
            f"""SELECT motif_class,
                       count(*) AS n,
                       count(*) FILTER (WHERE novel) AS novel
                FROM {loci_table} GROUP BY 1 ORDER BY n DESC"""
        ),
        "by_chrom": rows(
            f"""SELECT chrom,
                       count(*) AS n,
                       count(*) FILTER (WHERE novel) AS novel
                FROM {loci_table} GROUP BY 1
                ORDER BY {_CHROM_ORDER}"""
        ),
        # The tables this page is actually drawn from, not "is anything
        # registered synthetic". Once the loci table is resolved by role, a real
        # uploaded callset sits alongside the committed demo fixtures — and a
        # badge reading "synthetic demo data" over somebody's real results is a
        # worse failure than no badge at all.
        #
        # Both tables count, because both feed what is on screen, and they are
        # named rather than collapsed into the flag: registering a real locus
        # table without a matching segments table leaves real rows drawn with
        # fixture barcodes, and "one of these two" is the only honest way to say
        # so.
        "synthetic": bool(synthetic_tables),
        "synthetic_tables": synthetic_tables,
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
# Uploads
#
# A file handed to the interface lands in `settings.data_dir/uploads`, which is
# the same directory the registry already resolves manifest paths against — the
# /data bind mount under Docker, the repository's data/ without it. That is the
# whole trick: no branch in this file knows which one it is running under.
#
# Everything is addressed by upload id. A path never arrives from the network
# except through `link_path`, which confines it to the configured roots.
# --------------------------------------------------------------------------- #

def _upload_error(exc: uploads.UploadError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


def _upload_payload(upload: uploads.Upload) -> dict[str, Any]:
    """One upload as the interface needs it: the record, plus what could be done
    with it. The suggestions are computed here rather than in the browser so the
    dialog and the registration endpoint cannot disagree about what is legal."""
    payload = upload.public()
    payload["present"] = uploads.exists_on_disk(upload)
    if upload.kind == uploads.KIND_TABLE:
        columns = [c["name"] for c in upload.inspect.get("columns", [])]
        payload["suggested_name"] = uploads.suggest_dataset_name(upload.filename)
        payload["roles"] = {
            role: uploads.missing_for_role(columns, role)
            for role in ("loci", "segments")
        }
    return payload


@app.get("/api/uploads")
def list_uploads() -> dict[str, Any]:
    return {
        "enabled": settings.uploads_enabled,
        "directory": str(settings.uploads_dir),
        "max_upload_mb": settings.max_upload_mb,
        "accepted": list(uploads.ACCEPTED_EXTENSIONS),
        "uploads": [_upload_payload(u) for u in uploads.listing()],
    }


@app.post("/api/uploads", status_code=201)
async def create_upload(
    request: Request,
    filename: str = Query(..., description="The file's name, used for its type and label."),
) -> dict[str, Any]:
    """Stream one file to disk and report what it turned out to be.

    The body is the file itself, not a multipart form. Multipart would have
    Starlette spool the whole request to a temporary file before this function
    ever sees it, and then we would copy it again to its destination — 80 GB of
    disk traffic for a 40 GB VCF. Reading `request.stream()` writes it once.

    Blocking writes go to a worker thread so a slow disk cannot stall the event
    loop while the rest of the API is serving the page the upload is happening on.
    """
    try:
        writer = await run_in_threadpool(uploads.UploadWriter, filename)
    except uploads.UploadError as exc:
        raise _upload_error(exc) from exc

    try:
        async for chunk in request.stream():
            await run_in_threadpool(writer.write, chunk)
        upload = await run_in_threadpool(writer.finish)
    except uploads.UploadError as exc:
        await run_in_threadpool(writer.abort)
        raise _upload_error(exc) from exc
    except Exception:
        # Includes the client disconnecting mid-upload, which is what pressing
        # Cancel in the dialog does. Nothing partial is left behind.
        await run_in_threadpool(writer.abort)
        raise

    return _upload_payload(upload)


class LinkRequest(BaseModel):
    path: str


@app.post("/api/uploads/link", status_code=201)
def link_upload(request: LinkRequest) -> dict[str, Any]:
    """Register a file that is already on this machine, without copying it.

    The answer to a 40 GB VCF sitting beside the repository, and to running
    without Docker at all — where copying a file into a directory two levels up
    from where it already is would be the only thing "upload" meant.
    """
    try:
        return _upload_payload(uploads.link_path(request.path))
    except uploads.UploadError as exc:
        raise _upload_error(exc) from exc


@app.get("/api/uploads/{upload_id}")
def get_upload(upload_id: str) -> dict[str, Any]:
    try:
        return _upload_payload(uploads.get(upload_id))
    except uploads.UploadError as exc:
        raise _upload_error(exc) from exc


class RegisterRequest(BaseModel):
    name: str
    title: str = ""
    description: str = ""
    #: "loci" or "segments" to drive the catalog surface; "" to register a table
    #: the assistant can query but that no page reads.
    role: str = Field("", pattern="^(loci|segments)?$")


@app.post("/api/uploads/{upload_id}/register")
def register_upload(upload_id: str, request: RegisterRequest) -> dict[str, Any]:
    """Write the manifest for an upload and reload the registry.

    The reload is the point: a dataset becomes queryable without restarting the
    backend, which is what makes this an upload rather than a file copy plus a
    `docker compose restart`.
    """
    try:
        upload = uploads.get(upload_id)
        existing = registry.datasets.get(request.name)
        # Re-registering under the same name overwrites our own manifest, which
        # is how you fix a typo in a description. Colliding with someone else's
        # is a different thing: silently replacing a hand-written manifest from a
        # file upload would be the wrong call.
        if existing and existing.manifest_file != uploads.manifest_path(request.name).name:
            raise uploads.UploadError(
                f"{request.name!r} is already registered by "
                f"{existing.manifest_file}. Pick another name.",
                status=409,
            )
        uploads.write_manifest(
            upload, request.name, request.title, request.description, request.role
        )
    except uploads.UploadError as exc:
        raise _upload_error(exc) from exc

    registry.reload()
    uploads.set_dataset(upload_id, request.name)

    dataset = registry.datasets.get(request.name)
    if dataset is None or not dataset.available:
        # The manifest is written but the table did not load. Say why rather than
        # reporting success — the file is on disk either way.
        detail = dataset.error if dataset else "the manifest did not load"
        raise HTTPException(
            status_code=422,
            detail=f"Registered {request.name!r}, but it could not be read: {detail}",
        )
    return {"dataset": dataset.detail(), "upload": _upload_payload(uploads.get(upload_id))}


@app.delete("/api/uploads/{upload_id}")
def delete_upload(upload_id: str) -> dict[str, Any]:
    """Forget an upload, and unregister the dataset it produced.

    A linked upload's original file is never touched — we only ever held a
    record pointing at it.
    """
    try:
        upload = uploads.delete(upload_id)
    except uploads.UploadError as exc:
        raise _upload_error(exc) from exc

    unregistered = None
    if upload.dataset:
        manifest = uploads.manifest_path(upload.dataset)
        if manifest.exists():
            manifest.unlink()
            unregistered = upload.dataset
            registry.reload()
    return {"deleted": upload.id, "unregistered": unregistered}


@app.post("/api/registry/reload")
def reload_registry() -> dict[str, Any]:
    """Re-read the manifests. Also the escape hatch for a file dropped into
    `data/` by hand, which used to mean restarting the backend."""
    registry.reload()
    off = _off()
    return {
        "available": [d.name for d in registry.available_datasets(off)],
        "unavailable": [
            {"name": d.name, "error": d.error}
            for d in registry.datasets.values()
            if not d.available and d.name not in off
        ],
        "disabled": sorted(off),
        "roles": {role: registry.table_for(role, off) for role in ROLES},
    }


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
