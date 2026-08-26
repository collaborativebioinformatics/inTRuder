"""Tools exposed to the agent.

There are four, and the count does not grow with the number of datasets. Three are
generic data access over the registry; the fourth drives the visualization. A tool
per dataset would mean editing agent code every time somebody contributes a
manifest, and would grow the tool list without bound — see `data/web/README.md`.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from langchain_core.tools import tool

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
def set_view(
    novel_only: Annotated[bool | None, "Show only loci absent from every catalog."] = None,
    chrom: Annotated[str | None, "Restrict to one chromosome, e.g. 'chr4'. Use null to clear."] = None,
    motif_class: Annotated[
        Literal["homopolymer", "STR", "mid", "VNTR"] | None,
        "Restrict to one motif class. STR is 2-6bp, mid is 7-20bp, VNTR is >20bp.",
    ] = None,
    min_motif_len: Annotated[int | None, "Minimum motif length in bp."] = None,
    min_samples: Annotated[int | None, "Minimum number of carrier samples, out of 68."] = None,
    min_purity: Annotated[float | None, "Minimum mean repeat purity, 0-1."] = None,
    disease_gene_only: Annotated[bool | None, "Show only loci in known disease genes."] = None,
    gene: Annotated[str | None, "Restrict to one gene symbol, e.g. 'XYLT1'."] = None,
    focus_locus_id: Annotated[str | None, "Open one locus in the detail view, e.g. 'TRL000123'."] = None,
) -> str:
    """Change what the user is looking at in the browser.

    Call this whenever the user asks to see, show, filter, highlight, or open
    something — the interface is a view onto the same data you query with SQL, and
    this is how you move it. Pass only the fields you intend to change; omitted
    fields are left as they are. Explicitly pass null to clear a filter.

    Prefer calling this alongside your answer rather than instead of it: set the
    view so the user sees the loci, and say what they are looking at.
    """
    view = {
        key: value
        for key, value in {
            "novel_only": novel_only,
            "chrom": chrom,
            "motif_class": motif_class,
            "min_motif_len": min_motif_len,
            "min_samples": min_samples,
            "min_purity": min_purity,
            "disease_gene_only": disease_gene_only,
            "gene": gene,
            "focus_locus_id": focus_locus_id,
        }.items()
        if value is not None
    }
    if not view:
        return _dump({"applied": {}, "note": "No fields supplied; the view was left unchanged."})
    return _dump({"applied": view})


ALL_TOOLS = [list_datasets, describe_dataset, run_sql, set_view]
