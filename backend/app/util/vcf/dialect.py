"""Which field plays which role, decided from the header *and* the values.

Both sources are used because either alone is wrong somewhere. The header says
`AAL` is an "Alternative allele sequence" but not whether this file actually
carries one; the values say a key holds long nucleotide strings but not whether
it is the alt or the ref. Every role therefore ships with the evidence that
chose it, so a reader can tell an inference from a reading.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from app.util.vcf.common import _COORDINATE, _INTEGER, _MISSING, _NUCLEOTIDE
from app.util.vcf.header import FieldDef, Header


@dataclass
class FieldObservation:
    """What the values of one key actually looked like, over the learn window.

    A sample entry can hold a comma-separated list -- that is what `Number=.`
    means, and SURVIVOR uses it when one sample contributed two calls to a merged
    record. So each value is classified part-wise: the field counts as
    coordinate-valued when every part is a coordinate, not when the whole string
    happens to look like one.
    """

    seen: int = 0
    missing: int = 0
    nucleotide: int = 0
    numeric: int = 0
    coordinate: int = 0
    multi_valued: int = 0
    lengths: list[int] = field(default_factory=list)

    def add(self, value: str) -> None:
        self.seen += 1
        if value.lower() in _MISSING:
            self.missing += 1
            return
        parts = [p for p in value.split(",") if p.lower() not in _MISSING]
        if not parts:
            self.missing += 1
            return
        if len(parts) > 1:
            self.multi_valued += 1
        if all(_NUCLEOTIDE.match(p) for p in parts):
            self.nucleotide += 1
            self.lengths.append(max(len(p) for p in parts))
        if all(_INTEGER.match(p) for p in parts):
            self.numeric += 1
        if all(_COORDINATE.match(p) for p in parts):
            self.coordinate += 1

    @property
    def present(self) -> int:
        return self.seen - self.missing

    def fraction(self, count: int) -> float:
        return count / self.present if self.present else 0.0

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {"values_seen": self.seen, "not_called": self.missing}
        if self.present:
            out["nucleotide_like"] = self.nucleotide
            if self.multi_valued:
                out["entries_holding_a_list"] = self.multi_valued
            if self.lengths:
                out["median_length_bp"] = int(statistics.median(self.lengths))
                out["max_length_bp"] = max(self.lengths)
        return out


@dataclass
class Roles:
    """The keys this file uses for each role, and why each was chosen."""

    alt_sequence: str | None = None
    ref_sequence: str | None = None
    length: str | None = None
    coordinate: str | None = None
    source_id: str | None = None
    evidence: dict[str, str] = field(default_factory=dict)
    sequence_keys: list[str] = field(default_factory=list)


def _describes(definition: FieldDef | None, *words: str) -> bool:
    if definition is None:
        return False
    text = f"{definition.key} {definition.description}".lower()
    return any(word in text for word in words)


def detect_roles(header: Header, sample_values: dict[str, FieldObservation]) -> Roles:
    """Decide which FORMAT key plays which role, from the header and the values.

    Both sources are used because either alone is wrong somewhere. The header
    says `AAL` is an "Alternative allele sequence" but not whether the file
    actually carries one; the values say a key holds long nucleotide strings but
    not whether it is the alt or the ref. The evidence string records which of
    the two decided it, so a reader can tell an inference from a reading.
    """
    roles = Roles()
    if not sample_values:
        return roles

    # Sequence: mostly-nucleotide values, once the not-called markers are out.
    # This is why _MISSING matters -- SURVIVOR's `NAN` is A/C/G/T/N-only text.
    sequence_keys = [
        key
        for key, obs in sample_values.items()
        if obs.present and obs.fraction(obs.nucleotide) >= 0.9
    ]
    roles.sequence_keys = sequence_keys

    if sequence_keys:
        by_length = sorted(
            sequence_keys,
            key=lambda k: statistics.median(sample_values[k].lengths or [0]),
        )
        described_alt = [k for k in sequence_keys
                         if _describes(header.formats.get(k), "alternative", "alternate", "alt")]
        described_ref = [k for k in sequence_keys
                         if _describes(header.formats.get(k), "reference")]
        if described_alt and described_ref:
            roles.alt_sequence, roles.ref_sequence = described_alt[0], described_ref[0]
            roles.evidence["sequence"] = (
                f"header describes FORMAT/{roles.alt_sequence} as the alternate allele "
                f"and FORMAT/{roles.ref_sequence} as the reference allele"
            )
        elif len(by_length) >= 2:
            roles.alt_sequence, roles.ref_sequence = by_length[-1], by_length[0]
            roles.evidence["sequence"] = (
                f"no allele wording in the header; FORMAT/{roles.alt_sequence} holds the "
                f"longer values and FORMAT/{roles.ref_sequence} the shorter"
            )
        else:
            roles.alt_sequence = by_length[-1]
            roles.evidence["sequence"] = (
                f"FORMAT/{roles.alt_sequence} is the only nucleotide-valued sample field"
            )

    for key, obs in sample_values.items():
        definition = header.formats.get(key)
        if roles.coordinate is None and obs.present and obs.fraction(obs.coordinate) >= 0.9:
            roles.coordinate = key
            roles.evidence["coordinate"] = (
                f"{obs.coordinate}/{obs.present} observed FORMAT/{key} values are "
                f"chrom_position pairs"
                + (f'; header calls it "{definition.description}"' if definition and
                   definition.description else "")
            )
        if (roles.length is None and obs.present and obs.fraction(obs.numeric) >= 0.9
                and _describes(definition, "length", "len")):
            roles.length = key
            roles.evidence["length"] = (
                f'header calls FORMAT/{key} "{definition.description}" and '
                f"{obs.numeric}/{obs.present} observed values are integers"
            )
        if (roles.source_id is None and obs.present
                and _describes(definition, "sv id", "variant id", "sample sv")):
            roles.source_id = key
            roles.evidence["source_id"] = (
                f'header calls FORMAT/{key} "{definition.description}"'
            )
    return roles

