"""Uploads: storing a file, registering it, and letting it drive the catalog.

Every test runs against a temporary data directory, so nothing here touches the
repository's own `data/` — which matters more than usual, because the code under
test writes files and manifests into exactly that tree.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from app.config import REPO_ROOT, settings
from app.main import app
from app.util.registry import _pid_of, registry

DEMO_LOCI = REPO_ROOT / "data" / "web" / "demo" / "loci.parquet"
DEMO_SEGMENTS = REPO_ROOT / "data" / "web" / "demo" / "segments.parquet"


@pytest.fixture
def sandbox(tmp_path, request):
    """Point the app's data directory, registry and cache at a temp tree.

    `settings` is a frozen dataclass, so this goes through `object.__setattr__`
    rather than monkeypatch — and puts every attribute back afterwards, because
    the registry is a process-wide singleton shared with the other test module.
    """
    data_dir = tmp_path / "data"
    registry_dir = data_dir / "web"
    registry_dir.mkdir(parents=True)

    saved_settings = {
        name: getattr(settings, name)
        for name in ("data_dir", "registry_dir", "max_upload_mb", "upload_link_roots")
    }
    saved_registry = (registry.registry_dir, registry.cache_dir)

    object.__setattr__(settings, "data_dir", data_dir)
    object.__setattr__(settings, "registry_dir", registry_dir)
    registry.registry_dir = registry_dir
    registry.cache_dir = tmp_path / "cache"

    def restore():
        for name, value in saved_settings.items():
            object.__setattr__(settings, name, value)
        registry.registry_dir, registry.cache_dir = saved_registry
        registry.load()

    request.addfinalizer(restore)
    return tmp_path


@pytest.fixture
def client(sandbox):
    with TestClient(app) as test_client:
        yield test_client


def _loci_bytes(n_rows: int = 10) -> bytes:
    """A few rows of the demo locus table, as a parquet file in memory."""
    with duckdb.connect() as con:
        table = con.execute(
            f"SELECT * FROM read_parquet('{DEMO_LOCI}') LIMIT {n_rows}"
        ).to_arrow_table()
    sink = io.BytesIO()
    pq.write_table(table, sink)
    return sink.getvalue()


def _segments_bytes(n_rows: int = 20) -> bytes:
    """A few rows of the demo per-allele table, as a parquet file in memory."""
    with duckdb.connect() as con:
        table = con.execute(
            f"SELECT * FROM read_parquet('{DEMO_SEGMENTS}') LIMIT {n_rows}"
        ).to_arrow_table()
    sink = io.BytesIO()
    pq.write_table(table, sink)
    return sink.getvalue()


def _post(client: TestClient, filename: str, body: bytes):
    return client.post(f"/api/uploads?filename={filename}", content=body)


VCF = b"""\
##fileformat=VCFv4.2
##source=Sniffles2_2.2
##contig=<ID=chr1,length=248956422>
##INFO=<ID=SVTYPE,Number=1,Type=String,Description="Type">
##INFO=<ID=SUPP_VEC,Number=1,Type=String,Description="Support vector">
##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tHG00290\tHG00597
chr1\t1000\tINS0\tA\tACGTCGT\t60\tPASS\tSVTYPE=INS\tGT\t0/1\t1/1
"""


# --------------------------------------------------------------------------- #
# Storing
# --------------------------------------------------------------------------- #

def test_an_upload_lands_under_the_data_directory(client, sandbox):
    """The destination is derived from data_dir, which is what makes this work
    identically with and without Docker."""
    response = _post(client, "calls.vcf", VCF)
    assert response.status_code == 201, response.text
    body = response.json()

    stored = sandbox / "data" / "uploads" / body["id"] / "calls.vcf"
    assert stored.read_bytes() == VCF
    assert body["bytes"] == len(VCF)
    assert body["kind"] == "variants"
    assert body["present"] is True

    # The sidecar is the record; no database involved.
    meta = json.loads((stored.parent / "meta.json").read_text())
    assert meta["sha256"] == body["sha256"]


def test_a_traversal_filename_cannot_escape_the_uploads_directory(client, sandbox):
    response = _post(client, "..%2F..%2Fetc%2Fpasswd.csv", b"a,b\n1,2\n")
    assert response.status_code == 201, response.text

    directory = sandbox / "data" / "uploads" / response.json()["id"]
    written = [p for p in directory.iterdir() if p.name != "meta.json"]
    assert len(written) == 1
    assert written[0].parent == directory
    assert not (sandbox / "data" / "etc").exists()
    assert "/" not in response.json()["filename"]


def test_an_unsupported_type_is_refused_with_the_accepted_list(client):
    response = _post(client, "notes.txt", b"hello")
    assert response.status_code == 415
    # The message has to say what *would* work; "unsupported" alone sends the
    # person back to the docs.
    assert ".parquet" in response.json()["detail"]
    assert ".vcf.gz" in response.json()["detail"]


def test_an_oversize_upload_is_refused_and_leaves_nothing_behind(client, sandbox):
    """The cap is applied to the bytes as they arrive, not to Content-Length —
    a client that understates the header must not be able to fill the disk."""
    object.__setattr__(settings, "max_upload_mb", 0)
    response = _post(client, "big.csv", b"a,b\n" + b"1,2\n" * 1000)
    assert response.status_code == 413
    assert "MAX_UPLOAD_MB" in response.json()["detail"]

    uploads_dir = sandbox / "data" / "uploads"
    leftovers = list(uploads_dir.iterdir()) if uploads_dir.is_dir() else []
    assert leftovers == []


def test_an_empty_file_is_refused(client):
    assert _post(client, "empty.csv", b"").status_code == 400


# --------------------------------------------------------------------------- #
# Inspection
# --------------------------------------------------------------------------- #

def test_a_vcf_is_described_from_its_header(client):
    """The first half of `describe_vcf` (issue #59): what the file says it is,
    read from the header alone so the cost does not scale with the callset."""
    body = _post(client, "sniffles.vcf", VCF).json()
    inspected = body["inspect"]
    assert inspected["readable"] is True
    assert inspected["fileformat"] == "VCFv4.2"
    assert inspected["sources"] == ["Sniffles2_2.2"]
    assert inspected["n_samples"] == 2
    assert inspected["samples"] == ["HG00290", "HG00597"]
    # SUPP_VEC is the tell that several callers were merged into this file.
    assert inspected["merged"] is True


def test_a_table_reports_its_columns_and_a_preview(client):
    body = _post(client, "loci.parquet", _loci_bytes(10)).json()
    inspected = body["inspect"]
    assert inspected["readable"] is True
    assert inspected["n_rows"] == 10
    assert len(inspected["preview"]) == 5
    names = [c["name"] for c in inspected["columns"]]
    assert {"locus_id", "chrom", "pos", "motif"} <= set(names)
    # Whether it could play a role is decided on the server, so the dialog and
    # the register endpoint cannot disagree about what is legal.
    assert body["roles"]["loci"] == []
    assert body["roles"]["segments"], "a locus table is not a segments table"


# --------------------------------------------------------------------------- #
# Becoming a dataset
# --------------------------------------------------------------------------- #

def test_registering_makes_a_table_queryable_without_a_restart(client):
    """The point of the reload: a dataset appears while the process keeps running."""
    upload = _post(client, "mine.parquet", _loci_bytes(7)).json()
    assert client.get("/api/health").json()["datasets"]["available"] == []

    response = client.post(
        f"/api/uploads/{upload['id']}/register",
        json={"name": "my_calls", "title": "My calls", "description": "Mine."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["dataset"]["n_rows"] == 7
    assert "my_calls" in client.get("/api/health").json()["datasets"]["available"]


def test_a_registered_loci_table_drives_the_catalog(client):
    """The payoff. Registering with `role: loci` repoints the catalog surface —
    without it an upload changes nothing on screen, which reads as a no-op."""
    upload = _post(client, "cohort.parquet", _loci_bytes(9)).json()
    client.post(
        f"/api/uploads/{upload['id']}/register",
        json={"name": "cohort", "role": "loci"},
    )

    assert client.get("/api/summary").json()["funnel"][0]["count"] == 9
    assert client.get("/api/loci").json()["total"] == 9
    # `arrays` needs a segments table, and none is registered. The response must
    # report the order it is really in rather than the one that was asked for.
    assert client.get("/api/loci", params={"sort": "arrays"}).json()["sort"] == "position"


def test_the_synthetic_badge_follows_the_table_actually_being_read(client):
    """Registering a real callset must clear the badge, and it cannot be decided
    by asking whether *any* registered dataset is a fixture: the committed demo
    tables stay registered alongside it. A "synthetic demo data" badge over
    somebody's real results is worse than no badge."""
    upload = _post(client, "real.parquet", _loci_bytes(6)).json()
    client.post(
        f"/api/uploads/{upload['id']}/register",
        json={"name": "real_calls", "role": "loci"},
    )
    assert client.get("/api/summary").json()["synthetic"] is False


def test_a_real_locus_table_with_fixture_barcodes_names_which_half_is_fake(client):
    """Half-real is its own state. A locus table can be registered without a
    matching segments table, leaving real rows drawn with fixture barcodes — and
    a bare boolean would report that as "all of this is fake"."""
    loci = _post(client, "real.parquet", _loci_bytes(5)).json()
    client.post(
        f"/api/uploads/{loci['id']}/register", json={"name": "real_loci", "role": "loci"}
    )
    segments = _post(client, "fixture.parquet", _segments_bytes()).json()
    client.post(
        f"/api/uploads/{segments['id']}/register",
        json={"name": "fixture_segments", "role": "segments"},
    )

    body = client.get("/api/summary").json()
    assert body["synthetic"] is False, "neither upload is flagged synthetic"
    assert body["synthetic_tables"] == []


def test_a_table_missing_required_columns_cannot_claim_a_role(client):
    upload = _post(client, "notes.csv", b"a,b\n1,2\n").json()
    response = client.post(
        f"/api/uploads/{upload['id']}/register",
        json={"name": "notes", "role": "loci"},
    )
    assert response.status_code == 422
    assert "locus_id" in response.json()["detail"]
    # Refused for the role, but still registerable as a plain table.
    assert client.post(
        f"/api/uploads/{upload['id']}/register", json={"name": "notes"}
    ).status_code == 200


def test_a_vcf_cannot_be_registered_as_a_table(client):
    upload = _post(client, "calls.vcf", VCF).json()
    response = client.post(
        f"/api/uploads/{upload['id']}/register", json={"name": "calls"}
    )
    assert response.status_code == 409
    assert "TR-detection" in response.json()["detail"]


def test_an_invalid_dataset_name_is_refused_before_anything_is_written(client, sandbox):
    upload = _post(client, "mine.parquet", _loci_bytes(3)).json()
    response = client.post(
        f"/api/uploads/{upload['id']}/register", json={"name": "My Calls!"}
    )
    assert response.status_code == 422
    assert list((sandbox / "data" / "web").glob("*.yaml")) == []


def test_deleting_an_upload_unregisters_its_dataset(client, sandbox):
    upload = _post(client, "mine.parquet", _loci_bytes(4)).json()
    client.post(f"/api/uploads/{upload['id']}/register", json={"name": "mine"})
    assert "mine" in client.get("/api/health").json()["datasets"]["available"]

    body = client.delete(f"/api/uploads/{upload['id']}").json()
    assert body["unregistered"] == "mine"
    assert client.get("/api/health").json()["datasets"]["available"] == []
    assert not (sandbox / "data" / "uploads" / upload["id"]).exists()
    assert list((sandbox / "data" / "web").glob("*.yaml")) == []


def test_the_generated_manifest_says_its_prose_is_prompt_material(client, sandbox):
    """The description and column lines are what the agent is shown. A generated
    manifest that does not say so produces a table nobody can ask about."""
    upload = _post(client, "mine.parquet", _loci_bytes(2)).json()
    client.post(
        f"/api/uploads/{upload['id']}/register",
        json={"name": "mine", "description": "Real calls from our cohort."},
    )
    text = (sandbox / "data" / "web" / "upload-mine.yaml").read_text()
    assert "PROMPT MATERIAL" in text
    assert "Real calls from our cohort." in text
    assert "locus_id: (undocumented)" in text


# --------------------------------------------------------------------------- #
# Linking a file in place
# --------------------------------------------------------------------------- #

def test_a_file_already_on_disk_can_be_registered_without_copying(client, sandbox):
    """The answer to a 40 GB VCF, and to running with no container at all."""
    original = sandbox / "data" / "existing.vcf"
    original.write_bytes(VCF)

    body = client.post("/api/uploads/link", json={"path": str(original)}).json()
    assert body["linked"] is True
    assert body["inspect"]["n_samples"] == 2
    # No copy was made.
    assert not (sandbox / "data" / "uploads" / body["id"] / "existing.vcf").exists()

    # Forgetting a linked upload must never delete the original.
    client.delete(f"/api/uploads/{body['id']}")
    assert original.exists()


def test_a_relative_link_path_is_read_from_the_data_directory(client, sandbox):
    """Not from the process's working directory, which is `backend/` under
    `just dev` and `/app` in the container — the same string would find a
    different file in each."""
    (sandbox / "data" / "sv_output").mkdir(parents=True)
    (sandbox / "data" / "sv_output" / "merged.vcf").write_bytes(VCF)

    body = client.post("/api/uploads/link", json={"path": "sv_output/merged.vcf"})
    assert body.status_code == 201, body.text
    assert body.json()["inspect"]["n_samples"] == 2


def test_linking_refuses_a_path_outside_the_permitted_roots(client, tmp_path):
    """This endpoint has no authentication, and a registered dataset is readable
    by anyone with the chat box — an unconstrained path would be an
    arbitrary-file-read."""
    outside = tmp_path / "secrets.csv"
    outside.write_text("a,b\n1,2\n")

    response = client.post("/api/uploads/link", json={"path": str(outside)})
    assert response.status_code == 403
    assert "UPLOAD_LINK_ROOTS" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Registry mechanics the uploads depend on
# --------------------------------------------------------------------------- #

def test_reloading_does_not_disturb_a_query_already_in_flight(client):
    """A reload swaps a whole snapshot, so a cursor handed out microseconds
    earlier keeps working against the connection it came from."""
    upload = _post(client, "mine.parquet", _loci_bytes(5)).json()
    client.post(f"/api/uploads/{upload['id']}/register", json={"name": "mine"})

    cursor = registry.cursor().execute("SELECT locus_id FROM mine")
    registry.reload()
    assert len(cursor.fetchall()) == 5


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("registry-1234.duckdb", 1234),
        ("registry-1234-7.duckdb", 1234),
        ("registry-nonsense.duckdb", None),
    ],
)
def test_stale_database_files_are_still_recognised_after_the_reload_counter(
    name, expected
):
    """Reloading numbers the database files, so the pid is only the first field.
    Reading the whole stem as an integer would classify every file as
    unrecognised — and unrecognised files are deliberately never collected, so
    they would accumulate for the life of the machine."""
    assert _pid_of(Path(name)) == expected
