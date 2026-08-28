"""Files handed to the web interface: where they land, what we can say about
them, and how one becomes a registered dataset.

The whole point of this module is that the destination is
`settings.data_dir / "uploads"` and nothing more clever. Under Docker that
resolves inside the `/data` bind mount; under `just dev` it is the repository's
own `data/`. Both are already the directory the registry resolves manifest
paths against, so an uploaded file is reachable by a manifest the moment it
lands — with no branch anywhere asking whether we are in a container.

Nothing here trusts a name from the network. An upload is addressed by its id;
the id is matched against a strict pattern and joined to the uploads directory
here, and only here. That is the same boundary `registry.py` draws when it
disables external file access on the query connection: the client (and, later,
the model) names a handle, never a path.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
import secrets
import shutil
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

import duckdb

from app.config import settings

logger = logging.getLogger(__name__)

#: Upload ids. Generated here, but validated on the way back in — an id arrives
#: from the network and is about to be joined to a path.
_ID = re.compile(r"^[0-9a-f]{12}$")

#: What a filename is allowed to contain once we are done with it. Anything else
#: collapses to an underscore, so `../../etc/passwd` becomes a flat name and a
#: file called `; rm -rf /` is inert.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

#: The name a sanitized filename falls back to when nothing usable survives.
_FALLBACK_NAME = "upload.dat"

#: A dataset name, as `registry.py` requires it.
_DATASET_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")

#: What we accept, keyed by what we can actually do with it.
#:
#: `table` files become DuckDB tables and can be registered as datasets right
#: away. `variants` files are stored and described but are not tables: turning a
#: VCF into candidate loci is the TR-detection step, not an upload. Saying that
#: plainly is better than registering a VCF as a one-column table of text.
#:
#: BED is deliberately absent. It has no header row, and the manifest format has
#: no place to say so, so `read_csv_auto` would silently consume the first
#: feature as column names. Supporting it means read options in the manifest.
KIND_TABLE = "table"
KIND_VARIANTS = "variants"

_EXTENSIONS: dict[str, tuple[str, str]] = {
    ".parquet": (KIND_TABLE, "parquet"),
    ".csv": (KIND_TABLE, "csv"),
    ".csv.gz": (KIND_TABLE, "csv"),
    ".tsv": (KIND_TABLE, "tsv"),
    ".tsv.gz": (KIND_TABLE, "tsv"),
    ".vcf": (KIND_VARIANTS, ""),
    ".vcf.gz": (KIND_VARIANTS, ""),
    ".bcf": (KIND_VARIANTS, ""),
}

ACCEPTED_EXTENSIONS = tuple(sorted(_EXTENSIONS))

#: How much of a VCF header we are willing to read before deciding it is not one.
_MAX_HEADER_BYTES = 4 * 1024 * 1024

#: Rows shown in the confirm step, so the uploader can see it parsed as intended.
_PREVIEW_ROWS = 5


class UploadError(RuntimeError):
    """Something about the file or the request is wrong. Carries an HTTP status,
    because every one of these is reported to a person mid-upload and the
    difference between 'too big' and 'wrong type' matters to them."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- #
# Naming
# --------------------------------------------------------------------------- #

def split_extension(filename: str) -> str:
    """The accepted extension `filename` ends with, or "".

    Two-part extensions are checked first: `.csv.gz` is a compressed CSV, and
    matching `.gz` alone would lose the half that says how to read it.
    """
    lowered = filename.lower()
    for extension in sorted(_EXTENSIONS, key=len, reverse=True):
        if lowered.endswith(extension):
            return extension
    return ""


def sanitize_filename(filename: str) -> str:
    """A flat, harmless version of a filename supplied by a browser.

    Browsers send the base name, but nothing forces them to — this is called
    before the name is ever joined to a directory.
    """
    name = _UNSAFE.sub("_", Path(filename.strip()).name).strip("._-")
    return name or _FALLBACK_NAME


def suggest_dataset_name(filename: str) -> str:
    """A filename turned into something `registry.py` will accept as a table."""
    stem = filename[: len(filename) - len(split_extension(filename))] or filename
    slug = re.sub(r"[^a-z0-9_]+", "_", stem.lower()).strip("_")
    if not slug or not _DATASET_NAME.match(slug):
        slug = f"upload_{slug}".strip("_")
    return slug[:60] or "uploaded_dataset"


def validate_dataset_name(name: str) -> str:
    if not _DATASET_NAME.match(name):
        raise UploadError(
            f"{name!r} is not a usable table name. Use lowercase letters, digits "
            "and underscores, starting with a letter or underscore.",
            status=422,
        )
    return name


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #

@dataclass
class Upload:
    """One uploaded (or linked) file, as recorded in its `meta.json` sidecar.

    A sidecar per upload rather than a database: the uploads directory stays
    something a person can read, copy and delete with a file manager, which
    matters when the whole feature exists so that a bind mount is easy to reason
    about.
    """

    id: str
    filename: str
    bytes: int
    sha256: str
    uploaded_at: str
    kind: str
    format: str
    #: Absolute path to the data itself.
    path: str
    #: True when we point at a file in place instead of holding a copy. Deleting
    #: a linked upload removes our record, never the original.
    linked: bool = False
    #: The dataset name this was registered as, once it has been.
    dataset: str | None = None
    inspect: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        """What crosses the wire. The absolute path deliberately does not: it is
        an implementation detail on the server's disk, and for a linked upload it
        is somebody's home directory."""
        payload = asdict(self)
        payload.pop("path")
        return payload


def _uploads_dir() -> Path:
    return settings.uploads_dir


def _dir_for(upload_id: str) -> Path:
    if not _ID.match(upload_id):
        raise UploadError(f"No upload {upload_id!r}", status=404)
    return _uploads_dir() / upload_id


def ensure_dir() -> Path:
    """Create the uploads directory, reporting the fixable failure as fixable.

    The backend image runs as uid 10001 while `./data` on the host belongs to
    whoever cloned the repository. Docker Desktop papers over that; on Linux it
    is an EACCES, and a 500 with a traceback tells the person nothing about the
    one-line fix.
    """
    directory = _uploads_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise UploadError(
            f"Cannot write to {directory}. Under Docker the backend runs as uid "
            "10001; rebuild it as yourself with "
            "`docker compose build --build-arg UID=$(id -u) --build-arg "
            "GID=$(id -g) backend`, or make that directory writable.",
            status=500,
        ) from exc
    return directory


# --------------------------------------------------------------------------- #
# Inspection
# --------------------------------------------------------------------------- #

def _reader_expression(path: Path, fmt: str) -> str:
    quoted = str(path).replace("'", "''")
    if fmt == "parquet":
        return f"read_parquet('{quoted}')"
    if fmt == "tsv":
        return f"read_csv_auto('{quoted}', delim='\t')"
    return f"read_csv_auto('{quoted}')"


def inspect_table(path: Path, fmt: str) -> dict[str, Any]:
    """Columns, row count and a few rows, read through a throwaway connection.

    Explicitly *not* the registry's connection: that one is read-only with
    external access disabled, which is exactly what stops agent SQL reading
    arbitrary files, and reaching through it to look at a new upload would be
    dismantling the guarantee to save a connection.
    """
    reader = _reader_expression(path, fmt)
    try:
        with duckdb.connect() as con:
            described = con.execute(f"DESCRIBE SELECT * FROM {reader} LIMIT 0").fetchall()
            columns = [{"name": row[0], "type": row[1]} for row in described]
            n_rows = con.execute(f"SELECT count(*) FROM {reader}").fetchone()[0]
            cursor = con.execute(f"SELECT * FROM {reader} LIMIT {_PREVIEW_ROWS}")
            names = [d[0] for d in cursor.description]
            preview = [dict(zip(names, row)) for row in cursor.fetchall()]
    except duckdb.Error as exc:
        return {"readable": False, "error": str(exc)}
    return {
        "readable": True,
        "n_rows": n_rows,
        "columns": columns,
        "preview": preview,
    }


def _open_text(path: Path) -> BinaryIO:
    return gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")


def inspect_vcf(path: Path) -> dict[str, Any]:
    """What the VCF says about itself, from its header alone.

    Sample names, the callers that produced it and whether ALT carries literal
    sequence are the questions asked before anything reads the records — the
    first half of the `describe_vcf` capability in issue #59. Reading only the
    header keeps this O(header) on a file that may be tens of gigabytes.
    """
    if path.suffix == ".bcf":
        return {
            "readable": False,
            "note": "BCF is binary; its header is not read here. Convert to VCF "
                    "with `bcftools view` to see sample and source lines.",
        }

    sources: list[str] = []
    samples: list[str] = []
    contigs = 0
    info_keys: list[str] = []
    format_keys: list[str] = []
    fileformat = ""
    consumed = 0

    try:
        with _open_text(path) as handle:
            for raw in handle:
                consumed += len(raw)
                if consumed > _MAX_HEADER_BYTES:
                    break
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if not line.startswith("#"):
                    break
                if line.startswith("##fileformat="):
                    fileformat = line.split("=", 1)[1]
                elif line.startswith("##source="):
                    sources.append(line.split("=", 1)[1])
                elif line.startswith("##contig="):
                    contigs += 1
                elif line.startswith("##INFO=<ID="):
                    info_keys.append(line.split("##INFO=<ID=", 1)[1].split(",", 1)[0])
                elif line.startswith("##FORMAT=<ID="):
                    format_keys.append(line.split("##FORMAT=<ID=", 1)[1].split(",", 1)[0])
                elif line.startswith("#CHROM"):
                    fields = line.split("\t")
                    # Nine fixed columns come before the samples; a sites-only
                    # VCF stops at eight and has none.
                    samples = fields[9:] if len(fields) > 9 else []
                    break
    except OSError as exc:
        return {"readable": False, "error": str(exc)}

    return {
        "readable": bool(fileformat or samples),
        "fileformat": fileformat,
        "sources": sources,
        "n_samples": len(samples),
        # Enough to recognise the cohort without pasting 68 ids into a dialog.
        "samples": samples[:12],
        "samples_truncated": len(samples) > 12,
        "n_contigs": contigs,
        "info_keys": sorted(set(info_keys)),
        "format_keys": sorted(set(format_keys)),
        # SUPP_VEC is Jasmine/SURVIVOR's per-caller support vector: its presence
        # means this is a merged callset rather than one caller's output.
        "merged": "SUPP_VEC" in info_keys or "SUPP" in info_keys,
    }


def inspect(path: Path, kind: str, fmt: str) -> dict[str, Any]:
    if kind == KIND_TABLE:
        return inspect_table(path, fmt)
    if kind == KIND_VARIANTS:
        return inspect_vcf(path)
    return {}


# --------------------------------------------------------------------------- #
# Storing
# --------------------------------------------------------------------------- #

def classify(filename: str) -> tuple[str, str, str]:
    """`(extension, kind, format)` for an accepted filename, or a 415."""
    extension = split_extension(filename)
    if not extension:
        raise UploadError(
            f"Cannot use {filename!r}. Accepted file types: "
            f"{', '.join(ACCEPTED_EXTENSIONS)}.",
            status=415,
        )
    kind, fmt = _EXTENSIONS[extension]
    return extension, kind, fmt


def _write_meta(directory: Path, upload: Upload) -> None:
    (directory / "meta.json").write_text(json.dumps(asdict(upload), indent=2, default=str))


def new_id() -> str:
    return secrets.token_hex(6)


class UploadWriter:
    """Assembles one upload on disk, a chunk at a time.

    Split out from a single write-the-whole-file helper so the async endpoint and
    the synchronous tests drive exactly the same limit, hashing and cleanup logic
    rather than two copies of it that drift.

    The size limit is enforced *as chunks arrive* rather than from
    Content-Length, which a client is free to understate — a header check alone
    would let one fill the disk. The file is assembled under a `.part` name and
    renamed at the end, so a half-written upload never looks complete to
    anything listing the directory.
    """

    def __init__(self, filename: str):
        if not settings.uploads_enabled:
            raise UploadError(
                "Uploads are disabled on this server (UPLOADS_ENABLED).", status=403
            )
        _, self.kind, self.format = classify(filename)
        self.filename = sanitize_filename(filename)
        ensure_dir()

        self.id = new_id()
        self.directory = _uploads_dir() / self.id
        try:
            self.directory.mkdir(parents=True, exist_ok=False)
        except PermissionError as exc:
            raise UploadError(
                f"Cannot write to {self.directory.parent}. See the uid note in "
                "docker/README.md, or make that directory writable.",
                status=500,
            ) from exc

        self.target = self.directory / self.filename
        self._partial = self.directory / f"{self.filename}.part"
        self._handle = self._partial.open("wb")
        self._digest = hashlib.sha256()
        self.bytes = 0

    def write(self, chunk: bytes) -> None:
        if not chunk:
            return
        self.bytes += len(chunk)
        if self.bytes > settings.max_upload_bytes:
            raise UploadError(
                f"{self.filename} is larger than the {settings.max_upload_mb} MB "
                "limit. Raise MAX_UPLOAD_MB, or register the file in place instead "
                "of copying it through the browser.",
                status=413,
            )
        self._digest.update(chunk)
        try:
            self._handle.write(chunk)
        except OSError as exc:
            raise UploadError(f"Could not save {self.filename}: {exc}", status=500) from exc

    def finish(self) -> Upload:
        self._handle.close()
        if self.bytes == 0:
            raise UploadError(f"{self.filename} is empty.", status=400)
        self._partial.replace(self.target)

        upload = Upload(
            id=self.id,
            filename=self.filename,
            bytes=self.bytes,
            sha256=self._digest.hexdigest(),
            uploaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
            kind=self.kind,
            format=self.format,
            path=str(self.target),
            inspect=inspect(self.target, self.kind, self.format),
        )
        _write_meta(self.directory, upload)
        logger.info("stored upload %s (%s, %s bytes)", self.id, self.filename, self.bytes)
        return upload

    def abort(self) -> None:
        """Leave nothing behind. Called for a failed, cancelled or oversize upload."""
        try:
            self._handle.close()
        except OSError:
            pass
        shutil.rmtree(self.directory, ignore_errors=True)


def store_stream(filename: str, chunks) -> Upload:
    """Consume an iterable of bytes into a stored upload. The synchronous path,
    used by the tests; the endpoint drives `UploadWriter` directly so its writes
    can go to a worker thread."""
    writer = UploadWriter(filename)
    try:
        for chunk in chunks:
            writer.write(chunk)
        return writer.finish()
    except Exception:
        writer.abort()
        raise


def link_path(raw_path: str) -> Upload:
    """Record a file that is already on this machine, without copying it.

    The honest answer to a 40 GB VCF sitting beside the repository, and to
    running without Docker at all, where "upload" would otherwise mean copying a
    file to a directory two levels up from where it already is.

    The path is confined to the configured roots. This endpoint has no
    authentication, so an unconstrained path would turn it into an
    arbitrary-file-read for anything that can reach the port — a registered
    dataset is queryable by the agent, and by anyone with the chat box.
    """
    if not settings.uploads_enabled:
        raise UploadError("Uploads are disabled on this server (UPLOADS_ENABLED).", status=403)

    # A relative path is read against the data directory, not the process's
    # working directory. `data/sv_output/merged.vcf.gz` is what someone types,
    # and resolving that against wherever uvicorn happened to be started —
    # `backend/` under `just dev`, `/app` in the container — would mean the same
    # string finding a different file in each, or more often none at all.
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = settings.data_dir / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UploadError(
            f"No such file: {candidate}. Relative paths are read from "
            f"{settings.data_dir}.",
            status=404,
        ) from exc

    if not resolved.is_file():
        raise UploadError(f"{resolved} is not a file.", status=400)

    roots = settings.link_roots
    if not any(resolved.is_relative_to(root) for root in roots):
        listed = ", ".join(str(root) for root in roots)
        raise UploadError(
            f"{resolved} is outside the directories this server may read "
            f"({listed}). Move it under the data directory, or add its parent to "
            "UPLOAD_LINK_ROOTS.",
            status=403,
        )

    _, kind, fmt = classify(resolved.name)
    ensure_dir()
    upload_id = new_id()
    directory = _uploads_dir() / upload_id
    directory.mkdir(parents=True, exist_ok=False)

    upload = Upload(
        id=upload_id,
        filename=resolved.name,
        bytes=resolved.stat().st_size,
        # Not hashed: the file may be tens of gigabytes and we did not move it,
        # so there is nothing here worth verifying a copy against.
        sha256="",
        uploaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
        kind=kind,
        format=fmt,
        path=str(resolved),
        linked=True,
        inspect=inspect(resolved, kind, fmt),
    )
    _write_meta(directory, upload)
    logger.info("linked %s as upload %s", resolved, upload_id)
    return upload


# --------------------------------------------------------------------------- #
# Reading back
# --------------------------------------------------------------------------- #

def _read_meta(directory: Path) -> Upload | None:
    try:
        raw = json.loads((directory / "meta.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    known = {f for f in Upload.__dataclass_fields__}
    return Upload(**{k: v for k, v in raw.items() if k in known})


def get(upload_id: str) -> Upload:
    upload = _read_meta(_dir_for(upload_id))
    if upload is None:
        raise UploadError(f"No upload {upload_id!r}", status=404)
    return upload


def listing() -> list[Upload]:
    """Every recorded upload, newest first. Missing files are reported, not hidden."""
    directory = _uploads_dir()
    if not directory.is_dir():
        return []
    uploads = [
        upload
        for child in directory.iterdir()
        if child.is_dir() and _ID.match(child.name)
        for upload in [_read_meta(child)]
        if upload is not None
    ]
    return sorted(uploads, key=lambda u: u.uploaded_at, reverse=True)


def exists_on_disk(upload: Upload) -> bool:
    return Path(upload.path).exists()


def delete(upload_id: str) -> Upload:
    """Forget an upload. A linked file's original is never touched."""
    upload = get(upload_id)
    directory = _dir_for(upload_id)
    shutil.rmtree(directory, ignore_errors=True)
    logger.info("deleted upload %s (%s)", upload_id, upload.filename)
    return upload


def set_dataset(upload_id: str, dataset: str | None) -> Upload:
    upload = get(upload_id)
    upload.dataset = dataset
    _write_meta(_dir_for(upload_id), upload)
    return upload


# --------------------------------------------------------------------------- #
# Becoming a dataset
# --------------------------------------------------------------------------- #

#: Columns the catalog surface reads off a locus row. A table claiming
#: `role: loci` must carry them, or the page renders blanks — better to say so in
#: the dialog than to let someone register a table and meet an empty catalog.
LOCI_REQUIRED = ("locus_id", "chrom", "pos", "motif", "motif_len", "motif_class",
                 "n_samples", "median_len", "mean_purity", "novel")
SEGMENTS_REQUIRED = ("locus_id", "sample", "seg_index", "seg_type", "start", "end")

_ROLE_REQUIREMENTS = {"loci": LOCI_REQUIRED, "segments": SEGMENTS_REQUIRED}


def missing_for_role(columns: list[str], role: str) -> list[str]:
    """Which required columns a table lacks before it can play `role`."""
    required = _ROLE_REQUIREMENTS.get(role, ())
    present = {c.lower() for c in columns}
    return [c for c in required if c.lower() not in present]


def manifest_path(dataset: str) -> Path:
    return settings.registry_dir / f"upload-{dataset}.yaml"


def write_manifest(
    upload: Upload,
    dataset: str,
    title: str,
    description: str,
    role: str = "",
) -> Path:
    """Write the YAML that turns an upload into a registered dataset.

    Generated by hand rather than with yaml.dump so the file reads like the ones
    in `data/web` — comments and all — because a person is expected to open it
    and improve the prose. That prose is not documentation: `description` and the
    column lines are what the agent is shown when deciding whether this table can
    answer a question.
    """
    if upload.kind != KIND_TABLE:
        raise UploadError(
            f"{upload.filename} is a {upload.kind} file, not a table. A VCF becomes "
            "candidate loci by running the TR-detection step, not by registering it.",
            status=409,
        )
    validate_dataset_name(dataset)

    columns = [c["name"] for c in upload.inspect.get("columns", [])]
    if role:
        missing = missing_for_role(columns, role)
        if missing:
            raise UploadError(
                f"This table cannot play the {role!r} role — it is missing "
                f"{', '.join(missing)}.",
                status=422,
            )

    def quote(value: str) -> str:
        return json.dumps(value)

    lines = [
        f"# Generated from an upload of {upload.filename} on {upload.uploaded_at}.",
        "#",
        "# The description and column lines below are PROMPT MATERIAL: they are what",
        "# the assistant reads when deciding whether this table can answer a",
        "# question. Replacing the placeholders is the single highest-value edit you",
        "# can make to this file. See data/web/README.md.",
        f"name: {dataset}",
        f"title: {quote(title or dataset)}",
        f"path: {quote(upload.path)}",
        f"format: {upload.format}",
        "synthetic: false",
    ]
    if role:
        lines.append(f"role: {role}")
    lines += [
        "",
        "description: >",
    ]
    body = description.strip() or (
        f"Uploaded from {upload.filename}. No description was given, so the "
        "assistant knows only the column names — say what one row means and what "
        "the table is good for."
    )
    lines += [f"  {line}" for line in body.splitlines() or [""]]
    lines += ["", "columns:"]
    for column in columns:
        lines.append(f"  {column}: (undocumented)")
    lines += [
        "",
        "provenance:",
        f"  source: Uploaded via the web interface ({upload.filename})",
        f"  sha256: {upload.sha256 or 'not hashed (registered in place)'}",
        "",
    ]

    path = manifest_path(dataset)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
    logger.info("wrote manifest %s for upload %s", path.name, upload.id)
    return path
