"""Reading the records, and reading each one twice.

The point of the second reading is in `Accumulator._example`: an insertion is
extracted record-level (ALT minus its REF anchor, at POS) and per-sample (the
detected sequence field minus its anchor, at the detected breakpoint field), and
the two are compared. Where a dialect makes those disagree, the disagreement is
measured and named rather than asserted.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from itertools import chain, islice
from pathlib import Path
from typing import Any

from app.util.vcf.common import (
    _INTEGER,
    _MISSING,
    _NUCLEOTIDE,
    DEFAULT_MAX_RECORDS,
    LEARN_RECORDS,
    SAMPLE_FIELD_BUDGET,
    median_int,
)
from app.util.vcf.dialect import FieldObservation, Roles, detect_roles
from app.util.vcf.header import Header, read_header
from app.util.vcf.paths import open_text
from app.util.vcf.report import (
    field_report,
    notes,
    provenance,
    reference_guess,
    sample_summary,
)


def _stream_records(handle) -> Iterator[list[str]]:
    for line in handle:
        if line.startswith("#") or not line.strip():
            continue
        columns = line.rstrip("\n").split("\t")
        if len(columns) >= 8:
            yield columns


def _parse_info(field_text: str) -> dict[str, str]:
    info: dict[str, str] = {}
    if field_text in (".", ""):
        return info
    for entry in field_text.split(";"):
        if not entry:
            continue
        key, _, value = entry.partition("=")
        info[key] = value if _ else "true"
    return info


def _classify_alt(alt_field: str) -> tuple[str, list[str]]:
    """How this record represents its alternate allele."""
    if alt_field in (".", ""):
        return "missing", []
    alleles = alt_field.split(",")
    if any("[" in a or "]" in a for a in alleles):
        return "breakend", []
    symbolic = [a for a in alleles if a.startswith("<")]
    if symbolic:
        return "symbolic", symbolic
    if all(_NUCLEOTIDE.match(a) for a in alleles):
        return "literal_sequence", []
    return "other", []


def _is_called(genotype: str) -> bool:
    """Whether a sample carries the alternate allele at this record."""
    alleles = re.split(r"[/|]", genotype.split(":")[0])
    return any(a not in ("0", ".", "") for a in alleles)


def _sequence_preview(sequence: str, flank: int = 36) -> str:
    if len(sequence) <= 2 * flank + 3:
        return sequence
    return f"{sequence[:flank]}…{sequence[-flank:]}"


def _coordinate_positions(value: str) -> list[int]:
    """One start position per call in a coordinate value.

    Two separators are in play and they mean different things. `chr1_10712-chr1_10712`
    is the start and end of *one* call, so it contributes one position; a comma
    joins the coordinates of *two* calls, which SURVIVOR writes when a single
    sample contributed two variants to a merged record. Splitting on the comma
    first is what keeps a single call from reading as two — and the second call
    from disappearing.
    """
    positions = []
    for part in value.split(","):
        match = re.match(r"^\s*[\w.]+[_:](\d+)", part)
        if match:
            positions.append(int(match.group(1)))
    return positions


def _first_value(value: str) -> str:
    """The first live element of a possibly comma-separated sample value."""
    for part in value.split(","):
        if part.lower() not in _MISSING:
            return part
    return ""


def _summarize_insertion(alt: str, ref: str) -> tuple[str, bool]:
    """The inserted sequence: ALT with its REF anchor removed, if it is a prefix.

    Whether the anchor is really a prefix is checked rather than assumed -- the
    published TR table for this cohort is shifted by 68 bp because a caller
    stripped `len(ref)` where `ref` was the wrong string entirely.
    """
    if ref and alt.upper().startswith(ref.upper()):
        return alt[len(ref):], True
    return alt, False


def scan_vcf(path: Path, *, max_records: int = DEFAULT_MAX_RECORDS,
             n_examples: int = 5, root: Path | None = None) -> dict[str, Any]:
    """Read a VCF's header and a bounded prefix of its records, and report.

    Everything counted here is counted over the records actually read;
    ``scan.complete`` says whether that was the whole file.
    """
    stat = path.stat()
    with open_text(path) as handle:
        header = read_header(handle)
        n_samples = len(header.samples)

        # A wide file spends the budget on sample columns rather than on records.
        record_limit = max_records
        if n_samples > 1:
            record_limit = max(200, min(max_records, SAMPLE_FIELD_BUDGET // n_samples))

        records = _stream_records(handle)
        learn = list(islice(records, LEARN_RECORDS))
        learned = _learn_sample_values(header, learn)
        roles = detect_roles(header, learned)
        scan = Accumulator(header, roles, n_examples=n_examples)
        for columns in islice(chain(learn, records), record_limit):
            scan.add(columns)
        # islice stopped either because the file ran out or because the limit
        # did; one more pull from the generator is what tells the two apart.
        complete = next(records, None) is None

    report = scan.report()
    report["file"] = {
        "path": str(path.relative_to(root.resolve())) if root else str(path),
        "absolute_path": str(path),
        "size_bytes": stat.st_size,
        "compressed": path.name.endswith((".gz", ".bgz")),
        "vcf_version": (header.meta.get("fileformat") or ["unknown"])[0],
    }
    report["scan"] = {
        "records_scanned": scan.n_records,
        "complete": complete,
        "record_limit": record_limit,
        **({"limit_reduced_from": max_records,
            "limit_reason": f"{n_samples} sample columns per record"}
           if record_limit != max_records else {}),
    }
    report["reference"] = reference_guess(header)
    report["provenance"] = provenance(header, scan)
    report["samples"] = sample_summary(header)
    report["fields"] = field_report(header, roles, learned)
    report["notes"] = notes(header, roles, scan, complete)
    return report


def _learn_sample_values(header: Header, learn: list[list[str]]) -> dict[str, FieldObservation]:
    """Observe every FORMAT key's values across a small window of records."""
    observed: dict[str, FieldObservation] = {}
    for columns in learn:
        if len(columns) < 10:
            continue
        keys = columns[8].split(":")
        for column in columns[9:]:
            values = column.split(":")
            for key, value in zip(keys, values):
                observed.setdefault(key, FieldObservation()).add(value)
    return observed


class Accumulator:
    """One pass over the records, with the field roles already decided."""

    def __init__(self, header: Header, roles: Roles, *, n_examples: int = 5):
        self.header = header
        self.roles = roles
        self.n_examples = n_examples

        self.n_records = 0
        self.svtype = Counter()
        self.filters = Counter()
        self.alt_kinds = Counter()
        self.symbolic_alleles = Counter()
        self.info_keys = Counter()
        self.record_ids = Counter()
        self.caller_ids = Counter()
        self.svmethod = Counter()

        self.supp_vec_lengths = Counter()
        self.support_counts: list[int] = []

        # Where the two readings of the same record disagree.
        self.records_with_multiple_alleles = 0
        self.max_distinct_alleles = 0
        self.records_where_alt_matches_no_sample = 0
        self.records_with_shifted_breakpoint = 0
        self.breakpoint_offsets: list[int] = []
        self.records_comparable = 0
        self.records_with_anchor_mismatch = 0
        self.entries_with_several_coordinates = 0
        self.entries_with_several_alleles = 0

        self.examples: list[dict[str, Any]] = []

    # -- one record ------------------------------------------------------- #

    def add(self, columns: list[str]) -> None:
        self.n_records += 1
        chrom, pos_text, record_id, ref, alt = columns[0], columns[1], columns[2], columns[3], columns[4]
        filter_text, info_text = columns[6], columns[7]
        pos = int(pos_text) if _INTEGER.match(pos_text) else None

        info = _parse_info(info_text)
        for key in info:
            self.info_keys[key] += 1
        svtype = info.get("SVTYPE") or ""
        kind, symbolic = _classify_alt(alt)
        if not svtype and symbolic:
            svtype = symbolic[0].strip("<>")
        self.svtype[svtype or "(none)"] += 1
        self.filters[filter_text or "(none)"] += 1
        self.alt_kinds[kind] += 1
        for allele in symbolic:
            self.symbolic_alleles[allele] += 1
        if "SVMETHOD" in info:
            self.svmethod[info["SVMETHOD"]] += 1
        if record_id and record_id != ".":
            self.record_ids[record_id.split(".")[0]] += 1
        if "SUPP_VEC" in info:
            self.supp_vec_lengths[len(info["SUPP_VEC"])] += 1
            self.support_counts.append(info["SUPP_VEC"].count("1"))

        per_sample = self._per_sample(columns)
        self._compare(pos, ref, alt, per_sample)

        if len(self.examples) < self.n_examples and svtype == "INS" and kind != "breakend":
            self.examples.append(self._example(chrom, pos, record_id, ref, alt, kind,
                                               info, per_sample))

    def _per_sample(self, columns: list[str]) -> list[dict[str, Any]]:
        """The called samples' own view of this record, using the detected roles."""
        if len(columns) < 10 or not self.header.samples:
            return []
        keys = columns[8].split(":")
        out: list[dict[str, Any]] = []
        for name, column in zip(self.header.samples, columns[9:]):
            values = column.split(":")
            if not values or not _is_called(values[0]):
                continue
            fields = dict(zip(keys, values))
            entry: dict[str, Any] = {"sample": name, "genotype": values[0]}

            if self.roles.source_id:
                source = fields.get(self.roles.source_id, "")
                if source.lower() not in _MISSING:
                    entry["source_id"] = source
                    self.caller_ids[source.split(".")[0]] += 1
            if self.roles.length:
                declared = _first_value(fields.get(self.roles.length, ""))
                if _INTEGER.match(declared):
                    entry["declared_length"] = int(declared)
            if self.roles.coordinate:
                coordinate = fields.get(self.roles.coordinate, "")
                positions = _coordinate_positions(coordinate)
                if positions:
                    entry["coordinate"] = coordinate
                    entry["coordinate_positions"] = positions
                    if len(positions) > 1:
                        self.entries_with_several_coordinates += 1
            if self.roles.alt_sequence:
                raw_alt = fields.get(self.roles.alt_sequence, "")
                alt_value = _first_value(raw_alt)
                ref_value = _first_value(fields.get(self.roles.ref_sequence, "")) \
                    if self.roles.ref_sequence else ""
                if alt_value:
                    if "," in raw_alt.strip(","):
                        self.entries_with_several_alleles += 1
                    inserted, anchored = _summarize_insertion(alt_value, ref_value)
                    entry["allele"] = alt_value
                    entry["inserted"] = inserted
                    entry["anchor_removed"] = anchored
            out.append(entry)
        return out

    def _compare(self, pos: int | None, ref: str, alt: str,
                 per_sample: list[dict[str, Any]]) -> None:
        alleles = {e["allele"] for e in per_sample if "allele" in e}
        if alleles:
            self.records_comparable += 1
            if len(alleles) > 1:
                self.records_with_multiple_alleles += 1
            self.max_distinct_alleles = max(self.max_distinct_alleles, len(alleles))
            if alt.upper() not in {a.upper() for a in alleles}:
                self.records_where_alt_matches_no_sample += 1
            if any(e.get("anchor_removed") is False for e in per_sample if "allele" in e):
                self.records_with_anchor_mismatch += 1

        # One offset per carrier entry, and where an entry holds two coordinates
        # the nearest one is used: that cannot overstate how far the record POS
        # sits from where the sample actually places the breakpoint.
        entries = [e["coordinate_positions"] for e in per_sample
                   if e.get("coordinate_positions")]
        if pos is not None and entries:
            offsets = [min(abs(p - pos) for p in positions) for positions in entries]
            if any(offsets):
                self.records_with_shifted_breakpoint += 1
            self.breakpoint_offsets.extend(offsets)

    def _example(self, chrom, pos, record_id, ref, alt, kind, info,
                 per_sample) -> dict[str, Any]:
        """One record read both ways, with the differences spelled out."""
        inserted, anchored = _summarize_insertion(alt, ref) if kind == "literal_sequence" \
            else ("", False)
        record_level: dict[str, Any] = {
            "method": (
                "ALT with its REF anchor removed" if kind == "literal_sequence"
                else f"ALT is {alt!r}; it names a variant class and carries no sequence"
            ),
            "breakpoint": f"{chrom}:{pos}",
            "ref_column": ref if len(ref) <= 20 else f"{ref[:20]}… ({len(ref)} bp)",
        }
        if kind == "literal_sequence":
            record_level["inserted_bp"] = len(inserted)
            record_level["inserted_sequence"] = _sequence_preview(inserted)
            if not anchored:
                record_level["warning"] = "ALT does not start with REF; nothing was stripped"
        for key in ("SVLEN", "SVTYPE", "SUPP", "END"):
            if key in info:
                record_level.setdefault("info", {})[key] = info[key]

        carriers = [e for e in per_sample if "inserted" in e]
        sample_view: dict[str, Any] = {"n_called": len(per_sample)}
        if self.roles.alt_sequence and carriers:
            distinct = {e["inserted"] for e in carriers}
            sample_view["method"] = (
                f"FORMAT/{self.roles.alt_sequence} with its "
                f"FORMAT/{self.roles.ref_sequence} anchor removed"
                if self.roles.ref_sequence
                else f"FORMAT/{self.roles.alt_sequence}"
            )
            if self.roles.coordinate:
                sample_view["method"] += f", at the breakpoint in FORMAT/{self.roles.coordinate}"
            sample_view["carriers_with_sequence"] = len(carriers)
            sample_view["distinct_inserted_sequences"] = len(distinct)
            sample_view["inserted_bp_range"] = [
                min(len(s) for s in distinct), max(len(s) for s in distinct)
            ]
            sample_view["samples"] = [
                {
                    "sample": e["sample"],
                    "breakpoint": e.get("coordinate"),
                    "inserted_bp": len(e["inserted"]),
                    "declared_length": e.get("declared_length"),
                    "source_id": e.get("source_id"),
                    "inserted_sequence": _sequence_preview(e["inserted"]),
                }
                for e in carriers[:2]
            ]
        elif not self.header.samples:
            sample_view["method"] = "sites-only VCF: there are no sample columns"
        else:
            sample_view["method"] = (
                "no sample field carries sequence in this file; the record ALT is "
                "the only representation of the inserted bases"
            )

        disagreements: list[str] = []
        if carriers:
            positions = {p for e in carriers
                         for p in e.get("coordinate_positions", ())}
            shifted = {p for p in positions if p != pos}
            if shifted:
                offsets = sorted(abs(p - pos) for p in shifted)
                disagreements.append(
                    f"breakpoint: record POS is {pos:,}, carrier "
                    f"FORMAT/{self.roles.coordinate} positions are "
                    f"{', '.join(f'{p:,}' for p in sorted(shifted)[:3])}"
                    f" ({offsets[0]}-{offsets[-1]} bp away)"
                )
            distinct = {e["inserted"] for e in carriers}
            if len(distinct) > 1:
                disagreements.append(
                    f"alleles: {len(carriers)} carriers hold {len(distinct)} distinct "
                    f"inserted sequences; the record ALT is one representative"
                )
            if kind == "literal_sequence" and alt.upper() not in {
                e["allele"].upper() for e in carriers
            }:
                disagreements.append(
                    "the record ALT is not equal to any carrier's own allele"
                )
            declared = [e["declared_length"] for e in carriers
                        if e.get("declared_length") is not None]
            svlen = info.get("SVLEN", "")
            if declared and _INTEGER.match(svlen) and abs(int(svlen)) not in declared:
                disagreements.append(
                    f"length: INFO/SVLEN is {int(svlen):,} bp, carrier "
                    f"FORMAT/{self.roles.length} values run "
                    f"{min(declared):,}-{max(declared):,} bp"
                )

        return {
            "locus": f"{chrom}:{pos}",
            "id": record_id,
            "alt_representation": kind,
            "record_level": record_level,
            "per_sample": sample_view,
            "disagreements": disagreements,
        }

    # -- the report ------------------------------------------------------- #

    def report(self) -> dict[str, Any]:
        records: dict[str, Any] = {
            "svtype": dict(self.svtype.most_common(12)),
            "filter": dict(self.filters.most_common(6)),
            "alt_representation": dict(self.alt_kinds),
        }
        if self.symbolic_alleles:
            records["symbolic_alleles"] = dict(self.symbolic_alleles.most_common(8))
        out: dict[str, Any] = {"records": records, "examples": self.examples}

        merge = self._merge_report()
        if merge:
            out["merge"] = merge
        return out

    def _merge_report(self) -> dict[str, Any]:
        merge: dict[str, Any] = {}
        if self.supp_vec_lengths:
            merge["supp_vec"] = {
                "declared": True,
                "vector_lengths": dict(self.supp_vec_lengths),
                "matches_sample_count": (
                    set(self.supp_vec_lengths) == {len(self.header.samples)}
                ),
                "note": (
                    "one bit per merged input file, in the order of the sample columns"
                ),
            }
            if self.support_counts:
                merge["supp_vec"]["samples_supporting"] = {
                    "min": min(self.support_counts),
                    "median": median_int(self.support_counts),
                    "max": max(self.support_counts),
                    "singletons": sum(1 for c in self.support_counts if c == 1),
                }
        if self.records_comparable:
            merge["per_sample_vs_record"] = {
                "records_compared": self.records_comparable,
                "records_with_more_than_one_distinct_allele":
                    self.records_with_multiple_alleles,
                "most_distinct_alleles_at_one_record": self.max_distinct_alleles,
                "records_whose_ALT_matches_no_carrier": (
                    self.records_where_alt_matches_no_sample
                ),
            }
            if self.records_with_anchor_mismatch:
                merge["per_sample_vs_record"]["records_where_the_anchor_is_not_a_prefix"] = (
                    self.records_with_anchor_mismatch
                )
            if self.entries_with_several_alleles:
                merge["per_sample_vs_record"]["carrier_entries_holding_several_alleles"] = (
                    self.entries_with_several_alleles
                )
        if self.breakpoint_offsets:
            nonzero = [o for o in self.breakpoint_offsets if o]
            merge["breakpoint"] = {
                "records_where_a_carrier_sits_off_the_record_POS":
                    self.records_with_shifted_breakpoint,
                "carrier_entries_compared": len(self.breakpoint_offsets),
                "median_offset_bp_where_shifted": median_int(nonzero),
                "max_offset_bp": max(self.breakpoint_offsets),
            }
            if self.entries_with_several_coordinates:
                merge["breakpoint"]["carrier_entries_holding_several_coordinates"] = (
                    self.entries_with_several_coordinates
                )
                merge["breakpoint"]["note"] = (
                    "a carrier entry with two coordinates contributed two calls to "
                    "this merged record; the nearer coordinate was used above"
                )
        return merge

