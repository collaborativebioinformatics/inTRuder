"""Fetch the STRchive disease-locus catalog and flatten it for the web layer.

STRchive (<https://strchive.org>, Dashnow et al., Genome Medicine 2025) curates
the tandem-repeat loci where a repeat is known to cause human disease — 82 of
them at the pinned release. This script downloads that catalog, checksums it,
and writes a flat parquet the registry can serve to the agent as `strchive_loci`.

    cd backend && uv run python scripts/fetch_strchive.py

Why a flat parquet rather than the JSON as-is: STRchive nests motifs, evidence
and cross-references as lists, and DuckDB list columns are awkward for the SQL
an agent writes by hand. Lists become semicolon-joined strings, which `LIKE`
and `string_split` both handle, and the ranges stay numeric so they can be
compared against an estimated copy number.

The version and checksum below are deliberately the same pin as
`src/python/intruder/pipeline/strchive/catalog.py`, so the web layer and the pipeline step cannot
silently disagree about which release "STRchive says" refers to.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import pandas as pd

#: Pinned release. Bump this and STRCHIVE_SHA256 together — see STRCHIVE_COMPARE.md.
STRCHIVE_VERSION = "v2.26.0"
STRCHIVE_SHA256 = "306618801d03bb48eb69a206a9ea3d83dbbcc1317f7673a6f694c7de0b227794"

_URL = (
    "https://raw.githubusercontent.com/dashnowlab/STRchive/"
    "{version}/data/STRchive-loci.json"
)

OUT = Path(__file__).resolve().parents[2] / "data" / "web" / "strchive"

#: List-valued fields kept as semicolon-joined strings, and what each holds.
_JOINED = (
    "evidence",
    "inheritance",
    "association_type",
    "disease_tags",
    "locus_tags",
    "omim",
    "genereviews",
    "gnomad",
    "stripy",
    "tr_atlas",
    "medgen",
    "mondo",
    "orphanet",
)

#: Motif classes, reference orientation. STRchive also carries gene-orientation
#: copies; the reference orientation is the one that matches our coordinates.
_MOTIF_FIELDS = {
    "reference_motif": "reference_motif_reference_orientation",
    "pathogenic_motif": "pathogenic_motif_reference_orientation",
    "benign_motif": "benign_motif_reference_orientation",
    "unknown_motif": "unknown_motif_reference_orientation",
    "interruption_motif": "interruption_reference_orientation",
}


def _join(value) -> str:
    """A list field as a semicolon-joined string; empty string when absent."""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return ";".join(str(item) for item in value)


def download(version: str = STRCHIVE_VERSION) -> list[dict]:
    """Download the catalog and verify it against the pinned checksum.

    Falls back to the system `curl` where Python has no usable CA bundle — the
    same failure mode `src/python/intruder/pipeline/strchive/catalog.py` works around, and for the
    same reason (python.org builds on macOS, some HPC module stacks).
    """
    url = _URL.format(version=version)
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            raw = response.read()
    except Exception as exc:  # noqa: BLE001 - any TLS/network failure retries via curl
        print(f"[strchive] urllib failed ({exc}); retrying with curl", file=sys.stderr)
        raw = subprocess.run(
            ["curl", "-sSL", "--fail", url], capture_output=True, check=True
        ).stdout

    digest = hashlib.sha256(raw).hexdigest()
    if version == STRCHIVE_VERSION and digest != STRCHIVE_SHA256:
        raise SystemExit(
            f"checksum mismatch for {url}\n"
            f"  expected {STRCHIVE_SHA256}\n  got      {digest}"
        )
    if version != STRCHIVE_VERSION:
        print(
            f"[strchive] {version} is not the pinned release ({STRCHIVE_VERSION}); "
            f"checksum unverified, sha256={digest}",
            file=sys.stderr,
        )
    return json.loads(raw)


def flatten(records: list[dict], version: str = STRCHIVE_VERSION) -> pd.DataFrame:
    """One row per disease locus, with lists joined and ranges left numeric."""
    rows = []
    for record in records:
        row = {
            "id": record["id"],
            "disease_id": record.get("disease_id", ""),
            "gene": record.get("gene", ""),
            "disease": record.get("disease", ""),
            "disease_description": (record.get("disease_description") or "").strip(),
            "chrom": record.get("chrom", ""),
            "start_hg38": record.get("start_hg38"),
            "stop_hg38": record.get("stop_hg38"),
            "start_hg19": record.get("start_hg19"),
            "stop_hg19": record.get("stop_hg19"),
            "start_t2t": record.get("start_t2t"),
            "stop_t2t": record.get("stop_t2t"),
            "gene_strand": record.get("gene_strand") or "",
            "location_in_gene": record.get("location_in_gene") or "",
            "motif_len": record.get("motif_len"),
            "ref_copies": record.get("ref_copies"),
            "benign_min": record.get("benign_min"),
            "benign_max": record.get("benign_max"),
            "intermediate_min": record.get("intermediate_min"),
            "intermediate_max": record.get("intermediate_max"),
            "pathogenic_min": record.get("pathogenic_min"),
            "pathogenic_max": record.get("pathogenic_max"),
            # STRchive's own novelty call: is the *pathogenic* motif present in
            # hg38 at all? This is the same question the novelty screen asks,
            # arrived at independently by curation. 11 of 82 loci say no.
            "novel_in_reference": (record.get("novel") or "") == "novel",
            "novel_flag": record.get("novel") or "",
            "mechanism": record.get("mechanism") or "",
            "age_onset": record.get("age_onset") or "",
            "typ_age_onset_min": record.get("typ_age_onset_min"),
            "typ_age_onset_max": record.get("typ_age_onset_max"),
            "prevalence": record.get("prevalence") or "",
            "year": record.get("year") or "",
            "catalog_version": f"STRchive {version} (hg38)",
        }
        for out_name, source in _MOTIF_FIELDS.items():
            row[out_name] = _join(record.get(source))
        for field in _JOINED:
            row[field] = _join(record.get(field))
        rows.append(row)

    frame = pd.DataFrame(rows)
    # Sort by contig then position so the table reads in genomic order, the same
    # default the locus catalog uses.
    order = frame["chrom"].str.replace("chr", "", regex=False)
    frame = frame.assign(
        _c=order.replace({"X": "23", "Y": "24", "M": "25"}).astype(int)
    ).sort_values(["_c", "start_hg38"]).drop(columns="_c")
    return frame.reset_index(drop=True)


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else STRCHIVE_VERSION
    records = download(version)
    frame = flatten(records, version)

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "loci.parquet"
    frame.to_parquet(path, index=False)

    novel = int(frame["novel_in_reference"].sum())
    print(f"[strchive] {len(frame)} disease loci -> {path}")
    print(
        f"[strchive]   {novel} carry a pathogenic motif absent from hg38 "
        f"({novel / len(frame):.0%}) — the blind spot this pipeline targets"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
