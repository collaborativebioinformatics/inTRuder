"""The `##` header: what the file says about itself.

Parsed rather than trusted — every declaration here is a candidate that the
record scan then confirms against real values. See `dialect.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.util.vcf.common import _INTEGER, _META, _META_FIELD


@dataclass(frozen=True)
class FieldDef:
    """One ``##INFO`` or ``##FORMAT`` declaration."""

    key: str
    scope: str
    number: str = ""
    type: str = ""
    description: str = ""


@dataclass
class Header:
    meta: dict[str, list[str]] = field(default_factory=dict)
    info: dict[str, FieldDef] = field(default_factory=dict)
    formats: dict[str, FieldDef] = field(default_factory=dict)
    contigs: list[tuple[str, int | None]] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)
    column_line: str = ""


def _parse_meta_fields(body: str) -> dict[str, str]:
    """`<ID=CO,Number=1,Type=String,Description="Coordinates">` to a dict.

    Descriptions contain commas, so this matches key=value pairs rather than
    splitting on the separator.
    """
    inner = body.strip()
    if inner.startswith("<") and inner.endswith(">"):
        inner = inner[1:-1]
    out: dict[str, str] = {}
    for key, value in _META_FIELD.findall(inner):
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1].replace('\\"', '"')
        out[key] = value
    return out


def read_header(handle) -> Header:
    header = Header()
    for line in handle:
        if line.startswith("##"):
            match = _META.match(line.rstrip("\n"))
            if not match:
                continue
            kind, body = match.group(1), match.group(2)
            if kind in ("INFO", "FORMAT"):
                parsed = _parse_meta_fields(body)
                key = parsed.get("ID", "")
                if not key:
                    continue
                definition = FieldDef(
                    key=key,
                    scope=kind,
                    number=parsed.get("Number", ""),
                    type=parsed.get("Type", ""),
                    description=parsed.get("Description", ""),
                )
                (header.info if kind == "INFO" else header.formats)[key] = definition
            elif kind == "contig":
                parsed = _parse_meta_fields(body)
                length = parsed.get("length", "")
                header.contigs.append(
                    (parsed.get("ID", ""), int(length) if _INTEGER.match(length) else None)
                )
            else:
                header.meta.setdefault(kind, []).append(body)
        elif line.startswith("#CHROM"):
            header.column_line = line.rstrip("\n")
            columns = header.column_line.split("\t")
            header.samples = columns[9:] if len(columns) > 9 else []
            break
        else:
            # A data line before #CHROM: malformed, but the records are still
            # readable, so stop consuming the header rather than failing.
            break
    return header

