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

    return Dataset(
        name=name,
        title=str(raw.get("title", name)),
        description=str(raw.get("description", "")).strip(),
        path=_resolve_path(str(raw["path"]), registry_dir),
        format=fmt,
        columns={str(k): str(v) for k, v in (raw.get("columns") or {}).items()},
        provenance=raw.get("provenance") or {},
        synthetic=bool(raw.get("synthetic", False)),
        manifest_file=manifest_file.name,
    )


class Registry:
    """Loads manifests, materializes what exists, and serves guarded queries."""

    def __init__(self, registry_dir: Path | None = None, cache_dir: Path | None = None):
        self.registry_dir = registry_dir or settings.registry_dir
        self.cache_dir = cache_dir or (Path(__file__).resolve().parents[1] / ".cache")
        self.datasets: dict[str, Dataset] = {}
        self._con: duckdb.DuckDBPyConnection | None = None

    def load(self) -> None:
        self.datasets = {}
        if not self.registry_dir.is_dir():
            logger.warning("registry dir %s does not exist", self.registry_dir)
            return

        for manifest_file in sorted(self.registry_dir.glob("*.yaml")):
            try:
                dataset = _load_manifest(manifest_file, self.registry_dir)
            except (RegistryError, yaml.YAMLError) as exc:
                logger.error("skipping manifest %s: %s", manifest_file.name, exc)
                continue
            if dataset.name in self.datasets:
                logger.error(
                    "duplicate dataset name %r in %s; keeping the first",
                    dataset.name, manifest_file.name,
                )
                continue
            self.datasets[dataset.name] = dataset

        self._materialize()

    def _materialize(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        db_path = self.cache_dir / "registry.duckdb"
        if db_path.exists():
            db_path.unlink()

        # Phase 1: writable connection, load whatever is present on disk.
        with duckdb.connect(str(db_path)) as con:
            for dataset in self.datasets.values():
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
        self._con = duckdb.connect(str(db_path), read_only=True)
        try:
            self._con.execute("SET enable_external_access=false")
        except duckdb.Error as exc:  # pragma: no cover - depends on duckdb build
            logger.warning("could not disable external access: %s", exc)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            raise RegistryError("registry has not been loaded")
        return self._con

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
