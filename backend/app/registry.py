"""Dataset registry: YAML manifests in `data/web` become queryable DuckDB tables.

Adding a dataset is a manifest file, never a code change. See `data/web/README.md`.

Security note: the agent writes the SQL that runs here, so the query path is
deliberately narrow. Datasets are materialized into a DuckDB file at startup, the
file is then reopened **read-only**, and external file access is disabled on that
connection. The result is that agent-authored SQL can read the registered tables
and nothing else on disk. The tradeoff is memory: materializing suits the demo and
mid-sized callsets, but a multi-GB dataset should be switched to a view.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import yaml

from app.config import settings

logger = logging.getLogger(__name__)

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_READ_ONLY_PREFIX = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)

_READERS = {
    "parquet": "read_parquet",
    "csv": "read_csv_auto",
    "tsv": "read_csv_auto",
}

#: What a table *is*, as opposed to what it is called. The API renders the
#: candidate-locus surface from whichever registered table claims `role: loci`,
#: so uploading your own callset repoints the catalog without a code change and
#: without having to name your table `demo_loci`. Empty means "queryable by the
#: agent, not wired to a surface", which is the right answer for most datasets.
ROLES = ("loci", "segments")

#: Fallbacks, so a registry written before roles existed still drives the UI.
_ROLE_DEFAULTS = {"loci": "demo_loci", "segments": "demo_segments"}


def _pid_of(path: Path) -> int | None:
    """The pid encoded in a `registry-<pid>-<n>.duckdb` filename, if any.

    The `-<n>` counter exists because one process now materializes more than
    once — every upload reloads the registry — so the pid is only the first
    field. Reading the whole stem as an integer would classify every file as
    unrecognised, and unrecognised files are deliberately never collected.
    """
    stem = path.stem.removeprefix("registry-")
    pid = stem.split("-", 1)[0]
    return int(pid) if pid.isdigit() else None


def _pid_alive(pid: int | None) -> bool:
    """Whether a process still exists. A file whose owner is gone is collectable."""
    if pid is None:
        return True  # unrecognised name — leave it alone
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


@dataclass
class Dataset:
    name: str
    title: str
    description: str
    path: Path
    format: str
    columns: dict[str, str] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    synthetic: bool = False
    #: One of ROLES, or "" for a table that is queryable but drives no surface.
    role: str = ""
    manifest_file: str = ""
    available: bool = False
    n_rows: int | None = None
    error: str | None = None

    def summary(self) -> dict[str, Any]:
        """Compact form used by `list_datasets` — cheap enough to show them all."""
        return {
            "name": self.name,
            "title": self.title,
            "description": " ".join(self.description.split()),
            "synthetic": self.synthetic,
            "role": self.role,
            "available": self.available,
            "n_rows": self.n_rows,
            "columns": sorted(self.columns),
            **({"error": self.error} if self.error else {}),
        }

    def detail(self) -> dict[str, Any]:
        """Full form used by `describe_dataset`."""
        return {
            **self.summary(),
            "column_docs": self.columns,
            "provenance": self.provenance,
            "path": str(self.path),
            "manifest_file": self.manifest_file,
        }


class RegistryError(RuntimeError):
    pass


def _resolve_path(raw: str, registry_dir: Path) -> Path:
    """Manifest paths may be absolute, ~-relative, ${NOVELTRS_DATA_DIR}-relative,
    or relative to the manifest directory."""
    expanded = os.path.expandvars(raw).replace(
        "${NOVELTRS_DATA_DIR}", str(settings.data_dir)
    )
    path = Path(expanded).expanduser()
    if not path.is_absolute():
        path = registry_dir / path
    return path.resolve()


def _load_manifest(manifest_file: Path, registry_dir: Path) -> Dataset:
    raw = yaml.safe_load(manifest_file.read_text()) or {}

    name = str(raw.get("name", "")).strip()
    if not _IDENTIFIER.match(name):
        raise RegistryError(
            f"{manifest_file.name}: 'name' must be a lowercase SQL identifier, got {name!r}"
        )

    fmt = str(raw.get("format", "parquet")).lower()
    if fmt not in _READERS:
        raise RegistryError(
            f"{manifest_file.name}: unsupported format {fmt!r} "
            f"(supported: {', '.join(sorted(_READERS))})"
        )

    if not raw.get("path"):
        raise RegistryError(f"{manifest_file.name}: 'path' is required")

    role = str(raw.get("role", "")).strip().lower()
    if role and role not in ROLES:
        raise RegistryError(
            f"{manifest_file.name}: unknown role {role!r} "
            f"(supported: {', '.join(ROLES)}, or omit it)"
        )

    return Dataset(
        name=name,
        title=str(raw.get("title", name)),
        description=str(raw.get("description", "")).strip(),
        path=_resolve_path(str(raw["path"]), registry_dir),
        format=fmt,
        columns={str(k): str(v) for k, v in (raw.get("columns") or {}).items()},
        provenance=raw.get("provenance") or {},
        synthetic=bool(raw.get("synthetic", False)),
        role=role,
        manifest_file=manifest_file.name,
    )


@dataclass(frozen=True)
class _Snapshot:
    """One complete, self-consistent registry state.

    Reloading swaps this object in a single attribute assignment, which is what
    makes `reload()` safe under live traffic: a request either sees the whole
    old registry or the whole new one. Holding the dataset table and the
    connection as two separate attributes would leave a window where a caller
    reads a dataset that the connection it then asks does not have.
    """

    datasets: dict[str, Dataset]
    connection: duckdb.DuckDBPyConnection | None
    db_path: Path | None


_EMPTY_SNAPSHOT = _Snapshot(datasets={}, connection=None, db_path=None)


class Registry:
    """Loads manifests, materializes what exists, and serves guarded queries."""

    def __init__(self, registry_dir: Path | None = None, cache_dir: Path | None = None):
        self.registry_dir = registry_dir or settings.registry_dir
        self.cache_dir = cache_dir or (Path(__file__).resolve().parents[1] / ".cache")
        self._snapshot: _Snapshot = _EMPTY_SNAPSHOT
        # Serializes reloads against each other. Readers never take it — they
        # read `self._snapshot` once, which is atomic.
        self._lock = threading.RLock()
        self._generation = 0
        # Connections replaced by a reload, retired one generation late. See
        # `_retire`.
        self._retired: list[_Snapshot] = []

    # ----------------------------------------------------------------- state

    @property
    def datasets(self) -> dict[str, Dataset]:
        return self._snapshot.datasets

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        connection = self._snapshot.connection
        if connection is None:
            raise RegistryError("registry has not been loaded")
        return connection

    def cursor(self) -> duckdb.DuckDBPyConnection:
        """A private cursor over the same database.

        Always use this rather than the shared connection to run a query.
        FastAPI executes sync endpoints in a threadpool, so several requests run
        concurrently; a DuckDB connection carries one result set, and sharing it
        means a second `execute` silently invalidates the first caller's cursor
        mid-read. That surfaces as columns from someone else's query rather than
        as an error, which is far worse than a crash.
        """
        return self.connection.cursor()

    def available_datasets(self) -> list[Dataset]:
        return [d for d in self.datasets.values() if d.available]

    def table_for(self, role: str) -> str | None:
        """The table name claiming `role`, or the historical default.

        This is how an uploaded callset takes over the catalog surface: the API
        never names a table literally, it asks which one plays the part. A
        manifest that claims a role whose file is missing is ignored here rather
        than blanking the interface — an unavailable table cannot answer a query,
        so falling back to one that can is the honest behaviour.
        """
        datasets = self.datasets
        for dataset in datasets.values():
            if dataset.role == role and dataset.available:
                return dataset.name
        default = _ROLE_DEFAULTS.get(role)
        if default and default in datasets and datasets[default].available:
            return default
        return None

    # ------------------------------------------------------------- lifecycle

    def load(self) -> None:
        """(Re)read every manifest and materialize what is present on disk.

        Safe to call while requests are in flight — see `_Snapshot`. Callers who
        mean "pick up a manifest that appeared since startup" should say
        `reload()`; the two are the same call, and the name is the difference
        between describing setup and describing a refresh.
        """
        with self._lock:
            datasets = self._read_manifests()
            snapshot = self._materialize(datasets)
            previous, self._snapshot = self._snapshot, snapshot
            self._retire(previous)

    #: `load()` under the name that says what a second call is doing.
    reload = load

    def _read_manifests(self) -> dict[str, Dataset]:
        datasets: dict[str, Dataset] = {}
        if not self.registry_dir.is_dir():
            logger.warning("registry dir %s does not exist", self.registry_dir)
            return datasets

        for manifest_file in sorted(self.registry_dir.glob("*.yaml")):
            try:
                dataset = _load_manifest(manifest_file, self.registry_dir)
            except (RegistryError, yaml.YAMLError) as exc:
                logger.error("skipping manifest %s: %s", manifest_file.name, exc)
                continue
            if dataset.name in datasets:
                logger.error(
                    "duplicate dataset name %r in %s; keeping the first",
                    dataset.name, manifest_file.name,
                )
                continue
            datasets[dataset.name] = dataset

        for role in ROLES:
            claimants = [d.name for d in datasets.values() if d.role == role]
            if len(claimants) > 1:
                logger.warning(
                    "%d datasets claim role %r (%s); table_for() will pick the "
                    "first available one",
                    len(claimants), role, ", ".join(claimants),
                )
        return datasets

    def _materialize(self, datasets: dict[str, Dataset]) -> _Snapshot:
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # One database file per process *per load*. `uvicorn --reload` — which the
        # README tells you to run — starts the new worker before the old one
        # exits, and a shared filename means the new worker blocks forever trying
        # to open a DuckDB file the dying worker still holds. That surfaces as the
        # whole API hanging rather than as an error, so the filename carries the
        # pid. The counter is the same argument within one process: a reload must
        # not touch the file the outgoing connection is still serving from.
        self._generation += 1
        db_path = self.cache_dir / f"registry-{os.getpid()}-{self._generation}.duckdb"
        self._sweep_stale(keep=db_path)
        if db_path.exists():
            db_path.unlink()

        # Phase 1: writable connection, load whatever is present on disk.
        with duckdb.connect(str(db_path)) as con:
            for dataset in datasets.values():
                if not dataset.path.exists():
                    dataset.error = f"file not found: {dataset.path}"
                    logger.warning("dataset %s unavailable — %s", dataset.name, dataset.error)
                    continue
                reader = _READERS[dataset.format]
                args = f"'{dataset.path}'"
                if dataset.format == "tsv":
                    args += ", delim='\\t'"
                try:
                    con.execute(
                        f'CREATE TABLE "{dataset.name}" AS SELECT * FROM {reader}({args})'
                    )
                    dataset.n_rows = con.execute(
                        f'SELECT count(*) FROM "{dataset.name}"'
                    ).fetchone()[0]
                    dataset.available = True
                    # Columns absent from the manifest still need to be queryable.
                    described = con.execute(f'DESCRIBE "{dataset.name}"').fetchall()
                    for column_name, *_ in described:
                        dataset.columns.setdefault(column_name, "(undocumented)")
                    logger.info("registered %s (%s rows)", dataset.name, dataset.n_rows)
                except duckdb.Error as exc:
                    dataset.error = str(exc)
                    logger.error("failed to load %s: %s", dataset.name, exc)

        # Phase 2: reopen read-only and cut off the filesystem. Agent SQL runs here.
        connection = duckdb.connect(str(db_path), read_only=True)
        try:
            connection.execute("SET enable_external_access=false")
        except duckdb.Error as exc:  # pragma: no cover - depends on duckdb build
            logger.warning("could not disable external access: %s", exc)

        return _Snapshot(datasets=datasets, connection=connection, db_path=db_path)

    def _sweep_stale(self, keep: Path) -> None:
        """Delete database files left behind by processes that no longer exist."""
        for stale in self.cache_dir.glob("registry-*.duckdb"):
            if stale == keep:
                continue
            try:
                if not _pid_alive(_pid_of(stale)):
                    stale.unlink()
            except OSError:  # another process is mid-cleanup; harmless
                pass

    def _retire(self, previous: _Snapshot) -> None:
        """Close connections superseded by a reload, one generation behind.

        A request that got its cursor from the outgoing connection microseconds
        before the swap is still reading from it, so closing immediately would
        fail that request. Deferring by one reload is enough by a wide margin —
        reloads happen when a person uploads a file, not on a timer — and it
        bounds the number of open connections at two rather than trusting the
        garbage collector to notice.
        """
        retiring, self._retired = self._retired, [previous] if previous.connection else []
        for snapshot in retiring:
            try:
                if snapshot.connection is not None:
                    snapshot.connection.close()
                if snapshot.db_path is not None and snapshot.db_path.exists():
                    snapshot.db_path.unlink()
            except (duckdb.Error, OSError) as exc:
                logger.warning("could not retire %s: %s", snapshot.db_path, exc)

    def schema_prompt(self) -> str:
        """The block of text describing available tables that is injected into the
        agent's system prompt. This is what lets a new dataset become usable
        without touching agent code."""
        if not self.available_datasets():
            return "No datasets are currently available."

        lines: list[str] = []
        for dataset in self.available_datasets():
            flag = " [SYNTHETIC DEMO DATA]" if dataset.synthetic else ""
            lines.append(f'Table "{dataset.name}" — {dataset.title}{flag}')
            lines.append(f"  rows: {dataset.n_rows:,}")
            lines.append(f"  {' '.join(dataset.description.split())}")
            lines.append("  columns:")
            for column, doc in dataset.columns.items():
                lines.append(f"    - {column}: {doc}")
            lines.append("")
        return "\n".join(lines)

    def query(self, sql: str, max_rows: int | None = None) -> dict[str, Any]:
        """Run a single read-only statement and return rows plus column names.

        Raises RegistryError on anything that is not a lone SELECT/WITH statement.
        """
        max_rows = max_rows or settings.max_sql_rows
        stripped = sql.strip().rstrip(";")

        if not _READ_ONLY_PREFIX.match(stripped):
            raise RegistryError("only SELECT and WITH statements are permitted")
        if ";" in stripped:
            raise RegistryError("only a single statement is permitted")

        try:
            cursor = self.cursor().execute(stripped)
            columns = [description[0] for description in cursor.description]
            rows = cursor.fetchmany(max_rows + 1)
        except duckdb.Error as exc:
            raise RegistryError(str(exc)) from exc

        truncated = len(rows) > max_rows
        rows = rows[:max_rows]

        return {
            "columns": columns,
            "rows": [dict(zip(columns, row)) for row in rows],
            "row_count": len(rows),
            "truncated": truncated,
        }


registry = Registry()
