"""Assembling the report: the sections, and the verdict in sentences.

`notes` is the part the model reads first, so every sentence in it carries a
number that came out of the scan. Nothing here may state a fact the accumulator
did not count.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.util.vcf.common import _CHR1_LENGTHS, median_int
from app.util.vcf.dialect import FieldObservation, Roles
from app.util.vcf.header import Header

if TYPE_CHECKING:  # the accumulator imports this module, so only for annotations
    from app.util.vcf.scan import Accumulator


def reference_guess(header: Header) -> dict[str, Any]:
    lengths = {name: length for name, length in header.contigs}
    out: dict[str, Any] = {"n_contigs": len(header.contigs)}
    chr1 = lengths.get("chr1", lengths.get("1"))
    if chr1 in _CHR1_LENGTHS:
        out["assembly_guess"] = _CHR1_LENGTHS[chr1]
        out["evidence"] = f"chr1 is {chr1:,} bp in the ##contig header"
    elif chr1:
        out["assembly_guess"] = "unrecognized"
        out["evidence"] = f"chr1 is {chr1:,} bp, which matches no build known here"
    return out


def provenance(header: Header, scan: Accumulator) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if header.meta.get("source"):
        out["source_lines"] = header.meta["source"]
    if header.meta.get("command"):
        out["command_lines"] = [c[:300] for c in header.meta["command"][:3]]
    if scan.svmethod:
        out["svmethod"] = dict(scan.svmethod.most_common(5))
    if scan.caller_ids:
        out["callers_named_by_per_sample_ids"] = dict(scan.caller_ids.most_common(8))
    elif scan.record_ids:
        out["callers_named_by_record_ids"] = dict(scan.record_ids.most_common(8))
    return out


def sample_summary(header: Header) -> dict[str, Any]:
    names = header.samples
    layout = "sites-only" if not names else ("single-sample" if len(names) == 1
                                             else "multi-sample")
    out: dict[str, Any] = {"n": len(names), "layout": layout, "names": names[:40]}
    if len(names) > 40:
        out["names_omitted"] = len(names) - 40
    return out


def field_report(header: Header, roles: Roles,
                  observed: dict[str, FieldObservation]) -> dict[str, Any]:
    """Every FORMAT key with the role it plays, plus the evidence for the role."""
    role_of = {
        roles.alt_sequence: "sequence (alternate allele)",
        roles.ref_sequence: "sequence (reference anchor)",
        roles.length: "length",
        roles.coordinate: "breakpoint coordinate",
        roles.source_id: "originating caller's variant ID",
    }
    role_of.pop(None, None)

    format_fields = []
    for key, definition in header.formats.items():
        entry: dict[str, Any] = {
            "key": key,
            "type": definition.type,
            "number": definition.number,
            "description": definition.description,
        }
        if key in role_of:
            entry["role"] = role_of[key]
        if key in observed:
            entry["observed"] = observed[key].summary()
        format_fields.append(entry)

    return {
        "format": format_fields,
        "info": sorted(header.info),
        "roles": {
            "sequence_alt": roles.alt_sequence,
            "sequence_ref_anchor": roles.ref_sequence,
            "length": roles.length,
            "breakpoint": roles.coordinate,
            "source_id": roles.source_id,
        },
        "role_evidence": roles.evidence,
    }


def notes(header: Header, roles: Roles, scan: Accumulator,
           complete: bool) -> list[str]:
    """The verdict, in sentences, every one of them backed by a scanned number."""
    notes: list[str] = []
    n = len(header.samples)

    if n == 0:
        layout = "Sites-only VCF: no sample columns"
    elif n == 1:
        layout = f"Single-sample VCF ({header.samples[0]})"
    else:
        layout = f"Multi-sample VCF: {n} samples"
    if complete:
        notes.append(f"{layout}; {scan.n_records:,} records, the whole file.")
    else:
        notes.append(f"{layout}; the scan stopped after {scan.n_records:,} records, so "
                     f"every count here is of the records read, not of the file.")

    if scan.svmethod:
        method = ", ".join(scan.svmethod)
        notes.append(f"Merged callset: INFO/SVMETHOD is {method}"
                     + (f", contributed by {', '.join(scan.caller_ids)}"
                        if scan.caller_ids else "") + ".")

    literal = scan.alt_kinds.get("literal_sequence", 0)
    symbolic = scan.alt_kinds.get("symbolic", 0)
    if literal or symbolic:
        notes.append(
            f"ALT carries literal sequence in {literal:,} of {scan.n_records:,} scanned "
            f"records and a symbolic allele in {symbolic:,}"
            + (f" ({', '.join(scan.symbolic_alleles)})" if scan.symbolic_alleles else "")
            + "; symbolic records have no sequence to extract."
        )

    if roles.alt_sequence:
        anchor = (f", after removing the FORMAT/{roles.ref_sequence} anchor"
                  if roles.ref_sequence else "")
        notes.append(
            f"Per-sample inserted sequence lives in FORMAT/{roles.alt_sequence}{anchor}. "
            f"Read it there, not from the record ALT column."
        )
        if scan.records_with_multiple_alleles:
            notes.append(
                f"The record ALT is one representative allele: "
                f"{scan.records_with_multiple_alleles:,} of {scan.records_comparable:,} "
                f"compared records carry more than one distinct per-sample allele "
                f"(up to {scan.max_distinct_alleles} at a single record), and "
                f"{scan.records_where_alt_matches_no_sample:,} have an ALT that equals "
                f"no carrier's own allele."
            )
    elif header.samples:
        notes.append("No sample field carries sequence; the record ALT is the only "
                     "representation of the inserted bases.")

    if roles.coordinate and scan.breakpoint_offsets:
        nonzero = [o for o in scan.breakpoint_offsets if o]
        if nonzero:
            notes.append(
                f"Per-sample breakpoints live in FORMAT/{roles.coordinate} and do not "
                f"match record POS: {scan.records_with_shifted_breakpoint:,} of "
                f"{scan.records_comparable or scan.n_records:,} records have a carrier "
                f"offset from POS, median {median_int(nonzero)} bp, max "
                f"{max(nonzero):,} bp."
            )
        else:
            notes.append(f"FORMAT/{roles.coordinate} agrees with record POS at every "
                         f"carrier entry read.")
    return notes

