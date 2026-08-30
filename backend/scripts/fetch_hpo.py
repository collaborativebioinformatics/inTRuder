"""Fetch the HPO Consortium's gene-phenotype release and flatten it for the web layer.

`genes_to_phenotype.txt` (obophenotype/human-phenotype-ontology) is the official,
versioned join between HPO terms and the genes reported to cause them — Step 5 of
`docs/../phenotype_to_loci` (a validated HPO term id in, a gene list out) is a
straight SQL lookup against this table, once it is registered like any other
dataset. See `data/web/README.md`.

    cd backend && uv run python scripts/fetch_hpo.py

This is deliberately the twin of `fetch_strchive.py`: pin a release, checksum it,
write a flat parquet under `data/web/`, and let a manifest register it — no new
mechanism, no agent code change.

Unlike STRchive's JSON, this file is already flat (one row per gene x phenotype x
disease association), so there is no real "flatten" step, just a rename to match
this project's snake_case column convention and a dtype fix for the id columns.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import urllib.request
from pathlib import Path

import pandas as pd

#: Pinned release. Bump this and HPO_SHA256 together, the same discipline
#: fetch_strchive.py uses for its pin — "latest" is a moving target otherwise,
#: and a gene list that silently changes week to week is a bad thing to build an
#: agent tool on.
HPO_VERSION = "v2026-06-23"
HPO_SHA256 = "26cb7ee00c73b5777f6e5ad43323c941e1fcef1d191592f332d7929f3ea1ab3f"

_URL = (
    "https://github.com/obophenotype/human-phenotype-ontology/releases/"
    "download/{version}/genes_to_phenotype.txt"
)

OUT = Path(__file__).resolve().parents[2] / "data" / "web" / "hpo"


def download(version: str = HPO_VERSION) -> bytes:
    """Download the release and verify it against the pinned checksum.

    Falls back to `curl` where Python has no usable CA bundle, the same
    workaround `fetch_strchive.py` uses and for the same reason.
    """
    url = _URL.format(version=version)
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            raw = response.read()
    except Exception as exc:  # noqa: BLE001 - any TLS/network failure retries via curl
        print(f"[hpo] urllib failed ({exc}); retrying with curl", file=sys.stderr)
        raw = subprocess.run(
            ["curl", "-sSL", "--fail", url], capture_output=True, check=True
        ).stdout

    digest = hashlib.sha256(raw).hexdigest()
    if version == HPO_VERSION and digest != HPO_SHA256:
        raise SystemExit(
            f"checksum mismatch for {url}\n  expected {HPO_SHA256}\n  got      {digest}"
        )
    if version != HPO_VERSION:
        print(
            f"[hpo] {version} is not the pinned release ({HPO_VERSION}); "
            f"checksum unverified, sha256={digest}",
            file=sys.stderr,
        )
    return raw


def flatten(raw: bytes, version: str = HPO_VERSION) -> pd.DataFrame:
    """The release as a DataFrame, columns renamed to this project's convention.

    Real header (checked against the pinned release, not assumed):
    `ncbi_gene_id  gene_symbol  hpo_id  hpo_name  frequency  disease_id`
    Older HPO releases named the gene column `entrez_gene_symbol`; the current
    one calls it `gene_symbol` - renamed here so downstream code has one name to
    depend on regardless of which release produced the file.
    """
    import io

    frame = pd.read_csv(io.BytesIO(raw), sep="\t", dtype=str)
    frame = frame.rename(columns={"ncbi_gene_id": "gene_id"})
    frame["gene_id"] = pd.to_numeric(frame["gene_id"], errors="coerce").astype("Int64")
    frame["release_version"] = version
    return frame.reset_index(drop=True)


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else HPO_VERSION
    raw = download(version)
    frame = flatten(raw, version)

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "genes_to_phenotype.parquet"
    frame.to_parquet(path, index=False)

    n_genes = frame["gene_symbol"].nunique()
    n_terms = frame["hpo_id"].nunique()
    print(f"[hpo] {len(frame)} gene-phenotype rows -> {path}")
    print(f"[hpo]   {n_genes} distinct genes, {n_terms} distinct HPO terms, release {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
