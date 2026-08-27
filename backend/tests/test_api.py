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


def test_filters_needing_absent_columns_are_reported_not_silently_dropped(client):
    """A filter that cannot run must say so, not quietly match everything.

    `demo_loci` is one row per locus, so it has no `sample` column, and the
    STRchive step has not been run against it, so it has no `strchive_status`.
    Returning the full table while showing an active filter chip would read as a
    result, so those come back in `ignored_filters` instead.
    """
    baseline = client.get("/api/loci", params={"limit": 1}).json()
    filtered = client.get(
        "/api/loci",
        params={"limit": 1, "sample": "HG00597", "strchive_status": "pathogenic_motif"},
    ).json()
    assert filtered["total"] == baseline["total"]
    assert set(filtered["ignored_filters"]) == {"sample", "strchive_status"}
    assert baseline["ignored_filters"] == []


def test_reference_screen_filters_run_against_the_demo_fixtures(client):
    """The other half of the contract: a filter whose column *is* present must
    actually filter, and must not be reported as ignored.

    The demo fixtures carry the reference-screen columns (see
    scripts/make_demo_data.py), so `novelty`, `platform_agreement` and
    `min_insertion_purity` are real filters here rather than inert controls.
    """
    baseline = client.get("/api/loci", params={"limit": 1}).json()
    for params in (
        {"novelty": "novel_motif"},
        {"platform_agreement": "both"},
        {"min_insertion_purity": 0.8},
    ):
        body = client.get("/api/loci", params={"limit": 1, **params}).json()
        assert body["ignored_filters"] == [], params
        assert 0 < body["total"] < baseline["total"], params


def test_every_locus_carries_a_reference_verdict(client):
    """The locus view puts the reference at the top of the page, so a locus
    without per-catalog columns would render an empty comparison.

    `novelty` and `novel` are two views of one screen and must agree: `novel` is
    true exactly when the combined verdict is not `known`. A catalog that found
    nothing must report null, not zero -- "no repeat annotated here" and "a
    repeat of length zero" are different statements.
    """
    loci = client.get("/api/loci", params={"limit": 300}).json()["loci"]
    assert loci
    for locus in loci:
        assert locus["novelty"] in {"known", "novel_motif", "novel_locus"}
        assert locus["novel"] is (locus["novelty"] != "known")
        assert bool(locus["catalogs"]) is (locus["novelty"] == "known")
        for platform in ("ucsc", "trexplorer"):
            verdict = locus[f"{platform}_novelty"]
            assert verdict in {"known", "novel_motif", "novel_locus"}
            found = verdict != "novel_locus"
            assert (locus[f"{platform}_motif"] is not None) is found
            assert (locus[f"{platform}_start"] is not None) is found
            assert (locus[f"{platform}_n_nearby"] > 0) is found
        # The combined verdict is the least novel of the two, never more novel.
        rank = {"known": 0, "novel_motif": 1, "novel_locus": 2}
        assert rank[locus["novelty"]] == min(
            rank[locus["ucsc_novelty"]], rank[locus["trexplorer_novelty"]]
        )


def test_strchive_catalog_is_served(client):
    """The disease catalog is reference data and should be present on a clone
    that has run scripts/fetch_strchive.py."""
    summary = client.get("/api/strchive/summary")
    if summary.status_code == 503:
        pytest.skip("strchive_loci not fetched; run scripts/fetch_strchive.py")
    body = summary.json()
    assert body["n_loci"] == 82
    # The headline field: STRchive's own count of loci whose pathogenic motif is
    # absent from hg38. If this moves, the pinned release moved with it.
    assert body["n_novel_in_reference"] == 11
    assert body["screen"] is None or body["screen"]["available"] is True

    loci = client.get("/api/strchive/loci", params={"novel_in_reference": True}).json()
    assert loci["total"] == 11
    assert all(locus["novel_in_reference"] for locus in loci["loci"])
    assert {"RFC1", "SAMD12"} <= {locus["gene"] for locus in loci["loci"]}


def test_strchive_matches_reports_absence_rather_than_failing(client):
    """Not-yet-run is a state the page renders, not an error."""
    body = client.get("/api/strchive/matches").json()
    assert body["available"] in (True, False)
    if not body["available"]:
        assert body["note"]
        assert body["matches"] == []


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


@pytest.mark.parametrize(
    ("sort", "column"),
    [
        ("size", "median_len"),
        ("support", "n_samples"),
        ("motif_len", "motif_len"),
        ("purity", "mean_purity"),
    ],
)
def test_each_sort_orders_by_its_own_column_in_both_directions(client, sort, column):
    for sort_dir, ordered in (("desc", True), ("asc", False)):
        loci = client.get(
            "/api/loci", params={"limit": 50, "sort": sort, "sort_dir": sort_dir}
        ).json()["loci"]
        values = [row[column] for row in loci]
        assert values == sorted(values, reverse=ordered), (sort, sort_dir)


def test_sorting_by_repeat_arrays_matches_the_strip_the_row_draws(client):
    """`arrays` orders by how many repeat blocks are in the *representative*
    allele, which is the one the catalog row renders.

    Sorting by a number the row does not show would be a control with no visible
    effect, so the count and the strip come from one definition of that allele.
    """
    for sort_dir, ordered in (("desc", True), ("asc", False)):
        body = client.get(
            "/api/loci",
            params={
                "limit": 40,
                "sort": "arrays",
                "sort_dir": sort_dir,
                "include_strips": True,
            },
        ).json()
        assert body["sort"] == "arrays"
        drawn = [
            sum(1 for s in body["strips"][row["locus_id"]] if s["seg_type"] == "repeat")
            for row in body["loci"]
        ]
        assert drawn == sorted(drawn, reverse=ordered), sort_dir


def test_sort_reports_the_order_actually_applied(client):
    """The list must not claim an order it is not in.

    Direction defaults per key rather than globally — nobody asking to sort by
    size wants the smallest first, and nobody asking for position wants to start
    at the end of chrX.
    """
    assert client.get("/api/loci", params={"limit": 1}).json()["sort_dir"] == "asc"
    body = client.get("/api/loci", params={"limit": 1, "sort": "size"}).json()
    assert (body["sort"], body["sort_dir"]) == ("size", "desc")
    assert client.get("/api/loci", params={"limit": 1, "sort": "nope"}).status_code == 422


def test_sorting_does_not_change_which_loci_exist(client):
    """Ordering is not filtering: every sort returns the same population."""
    counts = {
        sort: client.get("/api/loci", params={"limit": 1, "sort": sort}).json()["total"]
        for sort in ("position", "novel", "size", "support", "arrays", "motif_len", "purity")
    }
    assert len(set(counts.values())) == 1, counts


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
