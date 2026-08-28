"""Shared vocabulary for reading a VCF: the limits, the patterns, the error.

Small on purpose. These constants are the assumptions the rest of the package
makes about VCF text, so they sit in one place where they can be read together
and changed once.
"""

from __future__ import annotations

import re
import statistics

#: How many data records a scan reads before it stops and says so. Everything
#: reported as a count or a fraction is "of the records scanned", never of the
#: file, unless `complete` is true.
DEFAULT_MAX_RECORDS = 2000

#: Records buffered before field roles are committed. Roles are decided from the
#: values in these, so one unrepresentative first record cannot mislead the scan;
#: they are then replayed through the same accumulator as everything after them.
LEARN_RECORDS = 25

#: Ceiling on per-sample field parses for one scan. A 69-sample file at the
#: default limit is ~138k, which is a second of work; a 5,000-sample file at the
#: same limit would be two orders of magnitude more, so the record limit gives
#: way instead and the report says it did.
SAMPLE_FIELD_BUDGET = 400_000

VCF_SUFFIXES = (".vcf", ".vcf.gz", ".vcf.bgz")

#: Values that mean "not called here". SURVIVOR writes `NAN` into its string
#: FORMAT fields, and `NAN` is a nucleotide string as far as a regex is
#: concerned -- so this set is load-bearing, not cosmetic.
_MISSING = {"", ".", "./.", ".|.", "nan", "na", "n/a", "--", "-"}

_NUCLEOTIDE = re.compile(r"^[ACGTNacgtn]+$")
_COORDINATE = re.compile(r"^[\w.]+[_:]\d+(?:-[\w.]+[_:]\d+)?$")
_META = re.compile(r"^##(\w+)=(.*)$", re.DOTALL)
_META_FIELD = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|[^,]*)')
_INTEGER = re.compile(r"^-?\d+$")

#: chr1 lengths, which differ between builds by enough to identify one. Reported
#: as a guess with its evidence, never as a fact read from the file: no VCF this
#: project handles states its reference assembly in a machine-readable way.
_CHR1_LENGTHS = {
    248956422: "GRCh38/hg38",
    249250621: "GRCh37/hg19",
    248387328: "T2T-CHM13v2.0",
    247249719: "NCBI36/hg18",
}


class VcfScanError(RuntimeError):
    """A path that cannot or must not be read, with a reason fit to show a user."""


def median_int(values: list[int]) -> int | None:
    """The median as a whole number, or None for an empty sample."""
    return int(statistics.median(values)) if values else None
