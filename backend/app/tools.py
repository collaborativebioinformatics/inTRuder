"""Tools exposed to the agent.

There are five, and the count does not grow with the number of datasets. Three are
generic data access over the registry; the fourth drives the visualization; the
fifth lists files someone has handed the interface. A tool per dataset would mean
editing agent code every time somebody contributes a manifest, and would grow the
tool list without bound — see `data/web/README.md`.

Note what is absent: nothing here takes a filesystem path. `run_sql` runs on a
connection with external file access disabled, and an upload is named by its id,
which is resolved to a path inside the uploads directory by `app.uploads` and
nowhere else. The model names handles; the server owns paths.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from langchain_core.tools import tool

from app import uploads
from app.registry import RegistryError, registry


def _dump(payload: Any) -> str:
    """Tool results go back to the model as text, so serialize predictably."""
    return json.dumps(payload, indent=2, default=str)


@tool
def list_datasets() -> str:
    """List every dataset registered in the data catalog.

    Returns each dataset's name, title, description, row count, column names, and
    whether its underlying file is present. Call this first when you are unsure
    what data exists. Datasets flagged synthetic are demo fixtures, not results.
    """
    datasets = [d.summary() for d in registry.datasets.values()]
    if not datasets:
        return _dump({"datasets": [], "note": "No manifests found in the registry directory."})
    return _dump({"datasets": datasets})


@tool
def describe_dataset(name: Annotated[str, "The dataset name, as returned by list_datasets."]) -> str:
    """Get the full schema for one dataset: per-column documentation, provenance,
    row count, and file path.

    Use this before writing SQL against a table you have not queried yet, so that
    column names and meanings come from the manifest rather than a guess.
    """
    dataset = registry.datasets.get(name)
    if dataset is None:
        known = sorted(registry.datasets)
        return _dump({"error": f"No dataset named {name!r}.", "available": known})
    return _dump(dataset.detail())


@tool
def run_sql(
    query: Annotated[str, "A single read-only DuckDB SELECT or WITH statement."],
) -> str:
    """Run a read-only DuckDB SQL query against the registered datasets.

    Only a single SELECT or WITH statement is permitted; there is no write access
    and no filesystem access. Results are capped, and the response reports whether
    truncation occurred. Prefer aggregate queries over dumping raw rows: to answer
    "how many novel loci are in disease genes", return a count, not 400 records.
    """
    try:
        result = registry.query(query)
    except RegistryError as exc:
        return _dump({"error": str(exc), "query": query})
    return _dump(result)


@tool
def list_uploads() -> str:
    """List the files someone has uploaded to this interface.

    Use this when the user refers to a file they have just given you — "the VCF I
    uploaded", "the callset I dropped in". Returns each file's id, name, size and
    what could be read from it: for a VCF that is its sample names, the callers
    named in its header and whether it is a merged callset; for a table, its
    columns.

    A file listed here with a `dataset` name is already queryable with `run_sql`
    under that name. One without is not a table yet — a VCF becomes candidate loci
    by running the TR-detection pipeline, which is not something you can do from
    here. Say that plainly rather than implying the data is available.
    """
    records = uploads.listing()
    if not records:
        return _dump({"uploads": [], "note": "Nobody has uploaded a file."})
    return _dump({"uploads": [u.public() for u in records]})


@tool
def set_view(
    page: Annotated[
        Literal["catalog", "strchive"] | None,
        "Which surface to show. 'catalog' is this cohort's candidate loci; "
        "'strchive' is the curated disease-locus reference and our screen against it.",
    ] = None,
    novel_only: Annotated[bool | None, "Show only loci absent from every catalog."] = None,
    novelty: Annotated[
        Literal["known", "novel_motif", "novel_locus"] | None,
        "The screen's three-valued verdict. 'novel_motif' means the reference has "
        "repeats here but none with this motif; 'novel_locus' means it annotates "
        "nothing here. Prefer this over novel_only when the user's question "
        "distinguishes the two.",
    ] = None,
    platform_agreement: Annotated[
        Literal["both", "ucsc_only", "trexplorer_only", "neither"] | None,
        "Restrict by how the reference catalogs compare. 'both' means UCSC and "
        "TRExplorer independently call it novel — the case worth trusting.",
    ] = None,
    chrom: Annotated[str | None, "Restrict to one chromosome, e.g. 'chr4'. Use null to clear."] = None,
    region: Annotated[
        str | None,
        "Restrict to a genomic range, e.g. 'chr3:1000-50000' (GRCh38, both ends "
        "inclusive). Keeps the loci whose insertion site falls inside it. Use "
        "chrom for a whole chromosome — this needs a range.",
    ] = None,
    motif_class: Annotated[
        Literal["homopolymer", "STR", "VNTR"] | None,
        "Restrict to one motif class. Homopolymer is a 1bp motif, STR is 2-6bp, "
        "VNTR is 7bp or longer.",
    ] = None,
    min_motif_len: Annotated[int | None, "Minimum motif length in bp."] = None,
    min_samples: Annotated[int | None, "Minimum number of carrier samples, out of 68."] = None,
    min_purity: Annotated[float | None, "Minimum mean repeat purity, 0-1."] = None,
    min_insertion_purity: Annotated[
        float | None,
        "Minimum fraction of the insertion that is tandem repeat at all, 0-1. "
        "Low values mean the insertion is mostly something else.",
    ] = None,
    disease_gene_only: Annotated[bool | None, "Show only loci in known disease genes."] = None,
    gene: Annotated[str | None, "Restrict to one gene symbol, e.g. 'XYLT1'."] = None,
    gene_query: Annotated[
        str | None,
        "Free-text gene search: keeps loci whose gene symbol contains this "
        "text, case-insensitively. Use it when the user is searching rather "
        "than naming a gene ('anything in the SYNE family'); prefer the exact "
        "`gene` when you know the symbol.",
    ] = None,
    sample: Annotated[str | None, "Restrict to one sample, e.g. 'HG00290'."] = None,
    strchive_status: Annotated[
        Literal[
            "pathogenic_expansion", "pathogenic_motif", "locus_novel_motif",
            "locus_known_motif", "no_locus_match",
        ] | None,
        "Restrict by the STRchive disease verdict.",
    ] = None,
    strchive_novel_only: Annotated[
        bool | None,
        "On the strchive page: show only the disease loci whose pathogenic motif "
        "is absent from hg38 (11 of 82).",
    ] = None,
    sort: Annotated[
        Literal["position", "novel", "size", "support", "arrays", "motif_len", "purity"]
        | None,
        "How to order the catalog list. 'position' is genomic order (the "
        "default), 'size' is median inserted-allele length, 'support' is how "
        "many samples carry it, 'arrays' is how many separate repeat blocks the "
        "drawn allele is built from (compound loci first), 'novel' puts loci "
        "absent from every catalog on top. Use this when the user asks for the "
        "biggest, the most common, or the most complex loci.",
    ] = None,
    sort_dir: Annotated[
        Literal["asc", "desc"] | None,
        "Sort direction. Omit for the natural one — descending for every sort "
        "except position, where ascending means the start of the chromosome.",
    ] = None,
    focus_locus_id: Annotated[str | None, "Open one locus in the detail view, e.g. 'TRL000123'."] = None,
    focus_strchive_id: Annotated[
        str | None,
        "Open one disease locus on the strchive page, e.g. 'CANVAS_RFC1'. "
        "Sets page to 'strchive' implicitly on the frontend.",
    ] = None,
) -> str:
    """Change what the user is looking at in the browser.

    Call this whenever the user asks to see, show, filter, highlight, or open
    something — the interface is a view onto the same data you query with SQL, and
    this is how you move it. Pass only the fields you intend to change; omitted
    fields are left as they are. Explicitly pass null to clear a filter.

    Prefer calling this alongside your answer rather than instead of it: set the
    view so the user sees the loci, and say what they are looking at.

    A filter needing a column the registered tables do not have is reported back
    as inactive in the interface rather than silently matching everything, so it
    is safe to set one before the screened callset exists — but say so.
    """
    view = {
        key: value
        for key, value in {
            "page": page,
            "novel_only": novel_only,
            "novelty": novelty,
            "platform_agreement": platform_agreement,
            "chrom": chrom,
            "region": region,
            "motif_class": motif_class,
            "min_motif_len": min_motif_len,
            "min_samples": min_samples,
            "min_purity": min_purity,
            "min_insertion_purity": min_insertion_purity,
            "disease_gene_only": disease_gene_only,
            "gene": gene,
            "gene_query": gene_query,
            "sample": sample,
            "strchive_status": strchive_status,
            "strchive_novel_only": strchive_novel_only,
            "sort": sort,
            "sort_dir": sort_dir,
            "focus_locus_id": focus_locus_id,
            "focus_strchive_id": focus_strchive_id,
        }.items()
        if value is not None
    }
    if not view:
        return _dump({"applied": {}, "note": "No fields supplied; the view was left unchanged."})
    return _dump({"applied": view})


ALL_TOOLS = [list_datasets, describe_dataset, run_sql, list_uploads, set_view]
