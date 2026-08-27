"""FastAPI application: data API for the visualization, SSE endpoint for the agent."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent import sse, stream_agent
from app.config import settings
from app.llm import describe_provider
from app.registry import registry

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


def _filter_clause(
    novel_only: bool,
    chrom: str | None,
    motif_class: str | None,
    min_motif_len: int | None,
    min_samples: int | None,
    min_purity: float | None,
    disease_gene_only: bool,
    gene: str | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
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
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


# Chromosomes sort as strings otherwise, which puts chr10 before chr2.
_CHROM_ORDER = (
    "CASE WHEN chrom = 'chrX' THEN 23 WHEN chrom = 'chrY' THEN 24 "
    "ELSE TRY_CAST(replace(chrom, 'chr', '') AS INTEGER) END"
)

_SORTS = {
    # Genomic order is the domain-native default, and it interleaves novel and
    # catalogued loci so the novel fraction reads as texture down the list.
    "position": f"{_CHROM_ORDER}, pos",
    "novel": f"novel DESC, motif_len DESC, {_CHROM_ORDER}, pos",
    "size": f"median_len DESC, {_CHROM_ORDER}, pos",
    "support": f"n_samples DESC, {_CHROM_ORDER}, pos",
}


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
    limit: int = Query(300, le=2000),
    offset: int = 0,
    include_strips: bool = False,
    sort: str = Query("position", pattern="^(position|novel|size|support)$"),
) -> dict[str, Any]:
    """Filtered locus list backing the catalog view.

    With `include_strips`, also returns the segment structure of one
    representative (median-length) allele per locus, so the catalog can render
    real motif barcodes rather than summary bars.
    """
    _require_loci()
    where, params = _filter_clause(
        novel_only, chrom, motif_class, min_motif_len,
        min_samples, min_purity, disease_gene_only, gene,
    )
    con = registry.cursor()
    total = con.execute(f"SELECT count(*) FROM demo_loci {where}", params).fetchone()[0]
    cursor = con.execute(
        f"""SELECT * FROM demo_loci {where}
            ORDER BY {_SORTS[sort]}
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
            f"""WITH allele AS (
                    SELECT locus_id, sample, max("end") AS allele_len
                    FROM demo_segments WHERE locus_id IN ({placeholders})
                    GROUP BY 1, 2
                ),
                ranked AS (
                    SELECT locus_id, sample,
                           row_number() OVER (PARTITION BY locus_id ORDER BY allele_len) AS rn,
                           count(*) OVER (PARTITION BY locus_id) AS n
                    FROM allele
                ),
                representative AS (
                    -- Integer division: DuckDB's `/` is float, so an even carrier
                    -- count would match no row at all.
                    SELECT locus_id, sample FROM ranked WHERE rn = (n + 1) // 2
                )
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
             "note": "No match in TR-Explorer, gnomAD-TR or STRchive"},
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
