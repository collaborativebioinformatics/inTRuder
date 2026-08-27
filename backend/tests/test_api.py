"""Smoke tests for the registry, the SQL sandbox, and the data API.

These run against the committed synthetic demo dataset, so they need no
credentials and no external data. Generate it first if it is missing:

    uv run python scripts/make_demo_data.py
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.registry import RegistryError, registry


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_demo_datasets_load(client):
    body = client.get("/api/health").json()
    assert set(body["datasets"]["available"]) >= {"demo_loci", "demo_segments"}


def test_a_manifest_without_its_file_degrades_rather_than_breaking(client):
    """Manifests are committed ahead of the data they describe.

    `strchive-calls.yaml` points at the screened callset the pipeline will
    produce; until that exists the dataset must report itself unavailable, with a
    usable reason, while everything else keeps serving.
    """
    body = client.get("/api/health").json()
    unavailable = {row["name"]: row["error"] for row in body["datasets"]["unavailable"]}
    for name, error in unavailable.items():
        assert error, f"{name} is unavailable without saying why"
    assert body["status"] == "ok"
    assert client.get("/api/summary").status_code == 200





def test_summary_funnel_is_monotonically_narrowing(client):
    counts = [stage["count"] for stage in client.get("/api/summary").json()["funnel"]]
    assert counts == sorted(counts, reverse=True)
    assert counts[0] > 0


def test_loci_filters_actually_filter(client):
    everything = client.get("/api/loci", params={"limit": 1}).json()["total"]
    novel = client.get("/api/loci", params={"limit": 1, "novel_only": True}).json()["total"]
    assert 0 < novel < everything


def test_every_returned_locus_has_a_strip(client):
    body = client.get(
        "/api/loci", params={"limit": 50, "include_strips": True}
    ).json()
    assert body["returned"] == 50
    # Regression: the representative-allele query used float division, so loci
    # with an even number of carriers matched no row and silently lost their strip.
    assert all(locus["locus_id"] in body["strips"] for locus in body["loci"])


def test_default_sort_is_genomic_not_lexicographic(client):
    chroms = [row["chrom"] for row in client.get("/api/summary").json()["by_chrom"]]
    assert chroms.index("chr2") < chroms.index("chr10")


def test_locus_detail_returns_all_carriers(client):
    locus_id = client.get("/api/loci", params={"limit": 1}).json()["loci"][0]["locus_id"]
    body = client.get(f"/api/loci/{locus_id}").json()
    assert len(body["alleles"]) == body["locus"]["n_samples"]
    assert all(allele["segments"] for allele in body["alleles"])


def test_unknown_locus_is_404(client):
    assert client.get("/api/loci/NOPE").status_code == 404


def test_chat_without_credentials_degrades_with_a_message(client):
    response = client.post(
        "/api/chat", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert response.status_code == 200
    # Either it streamed a real answer (a key is configured) or an actionable
    # configuration error — never a stack trace or an empty stream.
    assert "data:" in response.text


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE demo_loci",
        "CREATE TABLE evil AS SELECT 1",
        "SELECT 1; SELECT 2",
    ],
)
def test_sql_sandbox_rejects_writes_and_multiple_statements(client, sql):
    with pytest.raises(RegistryError):
        registry.query(sql)


def test_sql_sandbox_blocks_filesystem_access(client):
    with pytest.raises(RegistryError):
        registry.query("SELECT * FROM read_parquet('/etc/hosts')")


def test_sql_sandbox_caps_rows_and_reports_truncation(client):
    result = registry.query("SELECT * FROM demo_segments", max_rows=10)
    assert result["row_count"] == 10
    assert result["truncated"] is True
