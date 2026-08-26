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

def _require_loci() -> None:
    if "demo_loci" not in {d.name for d in registry.available_datasets()}:
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
    if include_strips and rows and "demo_segments" in {
        d.name for d in registry.available_datasets()
    }:
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
    if "demo_segments" in {d.name for d in registry.available_datasets()}:
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
