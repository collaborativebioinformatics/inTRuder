"""Switching a dataset off, and where the demo fixtures default to.

Three things are being pinned here.

The default: the committed demo tables exist so a fresh clone has something to
draw, and they have to get out of the way on their own the moment somebody
supplies a real callset — nobody is going to think to turn them off, and a
fabricated cohort sitting in the dataset list beside a real one is exactly the
sort of thing that ends up quoted.

What "off" means: not a hidden row. No surface draws it, the assistant is not
told it exists, and its rows are refused to agent-authored SQL. That last one is
the part worth a test, because every table stays materialized — one backend
serves many browsers — so the switch is enforced rather than achieved by absence.

Where the state lives: with the caller. One browser hiding the fixtures must not
hide them from anybody else, which is what `test_one_caller_does_not_move_another`
is for.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import REPO_ROOT
from app.main import app
from app.registry import Registry, RegistryError, registry
from app.switches import HEADER

DEMO_LOCI = REPO_ROOT / "data" / "web" / "demo" / "loci.parquet"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def off(*names: str) -> dict[str, str]:
    """The header a browser sends having switched `names` off."""
    return {HEADER: ",".join(f"{name}=off" for name in names)}


def _manifest(directory: Path, name: str, *, synthetic: bool, role: str = "") -> None:
    """A manifest pointing at the demo parquet.

    Which file it is does not matter — the default rule asks only whether the
    path exists — and reusing the committed fixture keeps these tests independent
    of whether anybody has downloaded the real callset.
    """
    lines = [
        f"name: {name}",
        f"title: {name}",
        f"synthetic: {str(synthetic).lower()}",
        f"path: {DEMO_LOCI}",
        "format: parquet",
        "description: A table.",
    ]
    if role:
        lines.append(f"role: {role}")
    (directory / f"{name}.yaml").write_text("\n".join(lines) + "\n")


# ------------------------------------------------------------------ defaults


def test_demo_fixtures_stay_on_when_nothing_real_drives_a_surface(client):
    """The fresh-clone case, and the one the rest of the suite runs under."""
    body = client.get("/api/datasets").json()
    datasets = {d["name"]: d for d in body["datasets"]}
    for name in ("demo_loci", "demo_segments"):
        assert datasets[name]["default_enabled"] is True, name
        assert datasets[name]["enabled"] is True, name
    assert body["roles"]["loci"] == "demo_loci"
    assert client.get("/api/summary").status_code == 200


def test_a_synthetic_table_defaults_off_once_real_data_claims_a_role(tmp_path):
    """The whole point of the default. A real callset registered with `role: loci`
    takes over the catalog surface, and the fixtures it displaced switch
    themselves off rather than lingering as a second cohort."""
    registry_dir = tmp_path / "web"
    registry_dir.mkdir()
    _manifest(registry_dir, "fixture_loci", synthetic=True)
    isolated = Registry(registry_dir=registry_dir, cache_dir=tmp_path / "cache")
    isolated.load()
    assert isolated.datasets["fixture_loci"].default_enabled is True
    assert isolated.switched_off({}) == frozenset()

    _manifest(registry_dir, "real_loci", synthetic=False, role="loci")
    isolated.load()
    assert isolated.datasets["fixture_loci"].default_enabled is False
    assert isolated.datasets["real_loci"].default_enabled is True
    assert isolated.switched_off({}) == {"fixture_loci"}
    assert isolated.table_for("loci", isolated.switched_off({})) == "real_loci"


def test_real_data_that_drives_no_surface_leaves_the_fixtures_alone(tmp_path):
    """"Provided data" means data that replaces the demo, not any real table.

    The disease-locus reference is real and always present, and registering it
    does not give the catalog anything to draw — so it must not be what turns the
    fixtures off.
    """
    registry_dir = tmp_path / "web"
    registry_dir.mkdir()
    _manifest(registry_dir, "fixture_loci", synthetic=True)
    _manifest(registry_dir, "reference", synthetic=False)  # real, but no role
    isolated = Registry(registry_dir=registry_dir, cache_dir=tmp_path / "cache")
    isolated.load()
    assert isolated.switched_off({}) == frozenset()


def test_a_role_claimed_by_a_manifest_whose_file_is_missing_changes_nothing(tmp_path):
    """A manifest committed ahead of its data must not switch the fixtures off.

    `strchive-calls.yaml` is exactly this shape. Turning the demo off on the
    strength of a file that has not arrived would leave the interface with
    nothing to draw at all.
    """
    registry_dir = tmp_path / "web"
    registry_dir.mkdir()
    # Named for the historical fallback in `_ROLE_DEFAULTS`, so this asserts the
    # end state a person would see: the catalog still has a table to draw.
    _manifest(registry_dir, "demo_loci", synthetic=True)
    (registry_dir / "future.yaml").write_text(
        "name: future_loci\ntitle: Not yet\nsynthetic: false\n"
        f"path: {tmp_path / 'nothing.parquet'}\nformat: parquet\nrole: loci\n"
        "description: The pipeline does not produce this yet.\n"
    )
    isolated = Registry(registry_dir=registry_dir, cache_dir=tmp_path / "cache")
    isolated.load()
    assert isolated.switched_off({}) == frozenset()
    assert isolated.table_for("loci", isolated.switched_off({})) == "demo_loci"


def test_an_override_beats_the_default_in_both_directions(tmp_path):
    """The default only decides where a switch starts."""
    registry_dir = tmp_path / "web"
    registry_dir.mkdir()
    _manifest(registry_dir, "fixture_loci", synthetic=True)
    _manifest(registry_dir, "real_loci", synthetic=False, role="loci")
    isolated = Registry(registry_dir=registry_dir, cache_dir=tmp_path / "cache")
    isolated.load()

    # On over a default of off, and off over a default of on.
    assert isolated.switched_off({"fixture_loci": True}) == frozenset()
    assert isolated.switched_off({"real_loci": False}) == {"fixture_loci", "real_loci"}
    # And nothing said means the default, which is what a first visit sends.
    assert isolated.switched_off({}) == {"fixture_loci"}


def test_a_switch_for_a_dataset_that_no_longer_exists_is_ignored(tmp_path):
    """A browser's stored switches outlive the registry they were set against."""
    registry_dir = tmp_path / "web"
    registry_dir.mkdir()
    _manifest(registry_dir, "fixture_loci", synthetic=True)
    isolated = Registry(registry_dir=registry_dir, cache_dir=tmp_path / "cache")
    isolated.load()
    assert isolated.switched_off({"deleted_last_week": False}) == frozenset()


# ------------------------------------------------------------------ the switch


def test_switching_off_takes_a_table_out_of_the_whole_interface(client):
    """Off reaches the surfaces, the assistant's schema, and its SQL."""
    header = off("demo_segments")

    health = client.get("/api/health", headers=header).json()["datasets"]
    assert "demo_segments" not in health["available"]
    assert health["disabled"] == ["demo_segments"]
    # Reported as switched off rather than as a manifest whose file is missing,
    # which is a different problem with a different fix.
    assert "demo_segments" not in {row["name"] for row in health["unavailable"]}

    # The barcodes surface has nothing to draw from...
    assert client.get("/api/datasets", headers=header).json()["roles"]["segments"] is None

    # ...and the assistant is not told it exists.
    hidden = registry.switched_off({"demo_segments": False})
    assert "demo_segments" not in registry.schema_prompt(hidden)


def test_switched_off_sql_is_refused_with_a_reason(client):
    """The other half of "off", and the half that would fail silently.

    Every table stays materialized — one backend serves every browser — so the
    switch cannot work by absence. The refusal names the table and says why,
    because the model reads it and would otherwise try again a different way.
    """
    hidden = registry.switched_off({"demo_segments": False})
    with pytest.raises(RegistryError, match="switched off"):
        registry.query("SELECT count(*) FROM demo_segments", off=hidden)
    # ...while everything still on is untouched.
    assert registry.query("SELECT count(*) FROM demo_loci", off=hidden)["row_count"] == 1


def test_one_caller_does_not_move_another(client):
    """The reason the state is local. Two browsers, one backend, one of them
    looking at the fixtures and the other not."""
    hidden = client.get("/api/datasets", headers=off("demo_loci")).json()
    plain = client.get("/api/datasets").json()

    assert {d["name"]: d["enabled"] for d in hidden["datasets"]}["demo_loci"] is False
    assert {d["name"]: d["enabled"] for d in plain["datasets"]}["demo_loci"] is True
    assert hidden["roles"]["loci"] is None
    assert plain["roles"]["loci"] == "demo_loci"


def test_the_catalog_reports_having_no_table_rather_than_crashing(client):
    """Every switch is movable, including the ones holding the page up. Turning
    the last locus table off has to say so, not 500."""
    response = client.get("/api/summary", headers=off("demo_loci"))
    assert response.status_code == 503
    assert "No candidate-locus dataset" in response.json()["detail"]
    assert client.get("/api/health").json()["status"] == "ok"


def test_a_malformed_header_falls_back_to_the_defaults(client):
    """A switch header is written by a browser we do not control the version of.
    Garbage in it must cost the defaults, not the request."""
    for value in ("", "demo_loci", "demo_loci=maybe", "=off,,,", "demo_loci=off=on"):
        body = client.get("/api/datasets", headers={HEADER: value}).json()
        enabled = {d["name"]: d["enabled"] for d in body["datasets"]}
        assert enabled["demo_loci"] is True, value
