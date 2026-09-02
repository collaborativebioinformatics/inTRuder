"""Pin the test suite to the committed demo fixtures.

These tests assert on demo-fixture contents — that four ataxins are searchable,
that every locus carries a reference verdict — so they only mean anything when
the demo tables are the ones the API is serving. That used to be true by
accident: nothing else claimed `role: loci`, so `_ROLE_DEFAULTS` fell through to
`demo_loci`.

It stopped being true the moment a real callset was registered beside them, and
would have stopped being true for anyone who pressed Upload and gave their own
table `role: loci` — the suite would start asserting demo facts against somebody
else's cohort and fail on their machine for a reason that has nothing to do with
their change. Whichever datasets happen to sit in `data/web` is not something a
test run should depend on.

So the registry is pointed at a directory holding only the manifests the suite is
written against. It is built out of symlinks rather than copies because manifest
paths resolve relative to the registry directory (`_resolve_path`), so the data
directories have to be reachable under the same relative names.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DIR = REPO_ROOT / "data" / "web"

#: The manifests the suite asserts against, plus the relative directories their
#: `path:` entries reach into. `strchive-calls.yaml` is here because one test is
#: specifically about a manifest whose file may be missing.
_MANIFESTS = (
    "demo-loci.yaml",
    "demo-segments.yaml",
    "strchive-loci.yaml",
    "strchive-calls.yaml",
    "hpo-gene-phenotype.yaml",
)
_DATA_DIRS = ("demo", "strchive", "hpo")


def _hermetic_registry() -> str:
    """A registry directory holding only `_MANIFESTS`, as symlinks."""
    staged = Path(tempfile.mkdtemp(prefix="intruder-test-registry-"))
    for name in _MANIFESTS:
        source = REGISTRY_DIR / name
        if source.exists():
            (staged / name).symlink_to(source)
    for name in _DATA_DIRS:
        source = REGISTRY_DIR / name
        if source.exists():
            (staged / name).symlink_to(source, target_is_directory=True)
    return str(staged)


# Set before anything imports `app.config`, which snapshots the environment into
# a frozen `Settings` at import time. pytest loads conftest ahead of the test
# modules that import the app, so this is the last moment it can be done.
os.environ.setdefault("INTRUDER_REGISTRY_DIR", _hermetic_registry())
os.environ.setdefault("INTRUDER_DATA_DIR", str(REPO_ROOT / "data"))
