"""The tool that reads a VCF file, as opposed to a registered dataset.

Every other tool answers from the registry: tables that somebody curated, wrote a
manifest for, and materialized into DuckDB. This one answers from a file nobody
has processed yet, which is why it exists — the first honest thing to say about a
VCF is what it is, and that has to be read out of the file rather than inferred
from the caller's name or from the last VCF anyone looked at.

Where the sequence lives differs by dialect, and getting it wrong is silent: read
a SURVIVOR-merged file the single-sample way and you still get sequence, just the
wrong sequence at a coordinate off by a median of 34 bp. So the report leads with
the disagreements between the two readings of the same record. See
`app.util.vcf`.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from app.config import settings
from app.tools.payload import dump
from app.util.vcf import VcfScanError, list_vcfs, resolve_vcf_path, scan_vcf


@tool
def describe_vcf(
    path: Annotated[
        str | None,
        "Path to a VCF, relative to the data directory (e.g. "
        "'sv_output/sniffles/raw/HG00290.raw.sniffles.vcf'). Omit it to list the "
        "VCF files available.",
    ] = None,
) -> str:
    """Report what a VCF file is, before anything reads sequence out of it.

    Returns: the samples and whether the file is single- or multi-sample; the
    callers behind it, from the header and from the per-sample variant IDs; how
    many records carry literal ALT sequence versus a symbolic allele like <INS>;
    which FORMAT keys hold the per-sample sequence, length and breakpoint, with
    the evidence that identified each; and five insertion records extracted both
    record-level and per-sample, with every disagreement between the two
    measured.

    Call this before answering any question about a VCF's contents, and before
    describing where its inserted sequence lives — the answer differs between a
    single-sample caller VCF and a merged multi-sample one, and the difference
    does not announce itself. Quote the numbers it returns rather than the
    dialect you expect.

    Call it with no path to see which VCF files are available.
    """
    root = settings.vcf_root
    if path is None:
        return dump({
            "data_root": str(root),
            "vcfs": list_vcfs(root),
            "note": "Pass one of these paths to describe it.",
        })

    try:
        resolved = resolve_vcf_path(path, root)
    except VcfScanError as exc:
        # An unreadable path comes back with the readable ones, the way
        # describe_dataset answers an unknown name with the known ones.
        return dump({
            "error": str(exc),
            "requested": path,
            "data_root": str(root),
            "available": list_vcfs(root),
        })

    try:
        report = scan_vcf(resolved, max_records=settings.vcf_max_records, root=root)
    except (OSError, UnicodeError) as exc:
        return dump({"error": f"could not read {path}: {exc}"})
    return dump(report)
