"""Generic data access over the dataset registry.

Three tools, and the count does not grow with the number of datasets: a tool per
dataset would mean editing agent code every time somebody contributes a manifest,
and would grow the tool list without bound. See `data/web/README.md`.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from app.tools.payload import dump
from app.util.registry import RegistryError, registry


@tool
def list_datasets() -> str:
    """List every dataset registered in the data catalog.

    Returns each dataset's name, title, description, row count, column names, and
    whether its underlying file is present. Call this first when you are unsure
    what data exists. Datasets flagged synthetic are demo fixtures, not results.
    """
    datasets = [d.summary() for d in registry.datasets.values()]
    if not datasets:
        return dump({"datasets": [], "note": "No manifests found in the registry directory."})
    return dump({"datasets": datasets})


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
        return dump({"error": f"No dataset named {name!r}.", "available": known})
    return dump(dataset.detail())


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
        return dump({"error": str(exc), "query": query})
    return dump(result)


