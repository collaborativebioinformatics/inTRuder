"""Shared fixtures for the STRchive step tests.

Tests never touch the network. ``data/strchive/STRchive-loci.mini.json`` holds
five real STRchive records copied verbatim from v2.26.0, chosen to cover the
awkward shapes the code has to survive:

    OPDM5_ABCD3   ordinary locus, reference motif == pathogenic motif
    CANVAS_RFC1   four pathogenic motifs, none of them the reference motif
    SCA37_DAB1    ref_copies == 0.0 (falsy but present)
    HMNR7_VWA1    ref_copies is null, and reference/pathogenic motifs are
                  rotations of one another
    FAME1_SAMD12  no benign range at all
"""

from __future__ import annotations

from pathlib import Path

import pytest

from intruder.pipeline.strchive.catalog import Catalog

#: Catalogues are data, so the fixture lives under ``data/`` with the rest of it
#: rather than beside the tests -- the same move the pathogenic TRGT catalogue
#: made to ``data/novelty/``. Resolved from the repo root the way
#: :func:`trcore.fetch.cache_root` does: tests/python/strchive -> repo.
FIXTURE = Path(__file__).resolve().parents[4] / "data" / "strchive" / "STRchive-loci.mini.json"


@pytest.fixture(scope="session")
def fixture_path() -> Path:
    return FIXTURE


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    return Catalog.from_file(FIXTURE, build="hg38", version="v2.26.0-test")


@pytest.fixture(scope="session")
def catalog_hg19() -> Catalog:
    return Catalog.from_file(FIXTURE, build="hg19", version="v2.26.0-test")
