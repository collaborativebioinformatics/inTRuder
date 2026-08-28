"""What the agent can do.

The count of data tools does not grow with the number of datasets — a tool per
dataset would mean editing agent code every time somebody contributes a manifest,
and would grow the tool list without bound. Contributors add a YAML manifest; the
agent surface is unchanged. See `data/web/README.md`.

    | module       | tools                                       |
    |--------------|---------------------------------------------|
    | `data`       | list_datasets, describe_dataset, run_sql    |
    | `view`       | set_view — moves the frontend               |
    | `vcf`        | describe_vcf — reads a file, not a table    |
    | `literature` | search_literature — reads Europe PMC, not us |
"""

from app.tools.data import describe_dataset, list_datasets, run_sql
from app.tools.literature import search_literature
from app.tools.vcf import describe_vcf
from app.tools.view import set_view

ALL_TOOLS = [
    list_datasets,
    describe_dataset,
    run_sql,
    set_view,
    describe_vcf,
    search_literature,
]

__all__ = [
    "ALL_TOOLS",
    "describe_dataset",
    "describe_vcf",
    "list_datasets",
    "run_sql",
    "search_literature",
    "set_view",
]
