"""Reading per-sample insertion alleles out of a merged SV VCF.

Everything a window needs -- the breakpoint and the inserted sequence -- lives in
the per-sample ``FORMAT`` fields, not in the record columns. A SURVIVOR-merged
VCF collapses one locus across samples into a single record, but keeps each
sample's original call intact underneath:

===========  ====================================================
``ID``       that sample's original Sniffles variant ID
``CO``       that sample's own breakpoint, ``chrom_pos-chrom_pos``
``RAL``      that sample's reference allele (the anchor base)
``AAL``      that sample's alternate allele: anchor + insertion
``LN``       that sample's insertion length
===========  ====================================================

Two things follow, and both were measured on
``data/sv_output/survivor_multi_sample_vcf/first_500_INS.vcf`` rather than
assumed:

**The record position is not the sample's breakpoint.** Checking each sample's
``RAL`` against hg38, it matches at the ``CO`` position for 6031/6148 entries
(98.1%) but at the record ``POS`` for only 3616/6148 (58.8%). 59% of entries sit
at a non-zero offset, median 34 bp and up to 704 bp. Since a junction span is
only +/-64 bp wide, taking the record position would displace it by half its
width for most samples.

**The alleles genuinely differ between samples.** 324 of 500 records carry more
than one distinct ``AAL``; ``chr1:10772`` has 37 called samples with 35 distinct
alleles between 52 and 78 bp. Using the record-level ``ALT`` would collapse all
37 into one and throw away the cross-sample consistency check.

.. warning::
   ``sv_trfcaller.py`` builds its insertion as ``AAL[s][len(RAL):]`` where
   ``RAL`` is the whole per-sample *array*, so it strips the sample count (69)
   rather than the anchor length (1). Its ``rep_start``/``rep_end`` are therefore
   offsets into a sequence missing its first 68 bases. This module does not
   reuse that expression -- see :func:`insertion_sequence` -- and callers should
   not trust those offsets until the upstream issue is settled.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import NamedTuple

MISSING = {"NaN", "NAN", "nan", ".", ""}

_CO = re.compile(r"^(?P<chrom>.+)_(?P<pos>\d+)$")


class InsertionCall(NamedTuple):
    """One sample's insertion allele at one merged locus."""

    chrom: str
    pos: int
    """The **sample's own** breakpoint, 1-based, from ``FORMAT/CO``."""

    record_pos: int
    """The merged record's ``POS``. Only useful for joining back to tables that
    were keyed on it, such as ``sv_trfcaller.py`` output."""

    sample: str
    svid: str
    """That sample's original caller ID, from ``FORMAT/ID``."""

    insert: str
    """The inserted bases: ``AAL`` with its ``RAL`` prefix removed."""

    declared_length: int
    """``FORMAT/LN``. Compared against ``len(insert)`` to catch a bad split."""

    @property
    def length_agrees(self) -> bool:
        return self.declared_length == len(self.insert)


def insertion_sequence(ral: str, aal: str) -> str:
    """Strip the reference allele from the alternate allele.

    The prefix removed is ``len(ral)`` -- the length of *this sample's* anchor,
    which is what makes this differ from ``sv_trfcaller.py``. When ``aal`` does
    not start with ``ral`` the record is malformed rather than merely short, so
    nothing is stripped and the caller sees it via ``length_agrees``.
    """
    if not aal.startswith(ral):
        return aal
    return aal[len(ral) :]


def parse_co(co: str) -> tuple[str, int] | None:
    """Left breakpoint of a ``CO`` field like ``chr1_10712-chr1_10712``.

    Contig names may themselves contain ``_`` (``chr14_GL000009v2_random``), so
    the split is on the *last* underscore, not the first.
    """
    left = co.split("-", 1)[0]
    m = _CO.match(left)
    if not m:
        return None
    return m["chrom"], int(m["pos"])


def read_insertions(path: str, svtype: str = "INS") -> Iterator[InsertionCall]:
    """Yield one :class:`InsertionCall` per called sample per INS record.

    Plain-text parsing rather than cyvcf2: the fields wanted here are all
    strings, and cyvcf2's ``variant.format()`` returns a per-sample *array*
    whose length is the sample count -- the exact shape that produced the
    ``sv_trfcaller.py`` truncation. Reading the columns directly removes the
    opportunity to make that mistake.
    """
    opener = open
    if path.endswith(".gz"):
        import gzip

        opener = gzip.open

    with opener(path, "rt") as fh:
        samples: list[str] = []
        for line in fh:
            if line.startswith("##"):
                continue
            fields = line.rstrip("\n").split("\t")
            if line.startswith("#CHROM"):
                samples = fields[9:]
                continue
            if f"SVTYPE={svtype}" not in fields[7]:
                continue

            keys = fields[8].split(":")
            try:
                i_id, i_ral, i_aal, i_ln, i_co = (
                    keys.index(k) for k in ("ID", "RAL", "AAL", "LN", "CO")
                )
            except ValueError:  # a record without the SURVIVOR fields
                continue

            record_pos = int(fields[1])
            for sample, cell in zip(samples, fields[9:]):
                parts = cell.split(":")
                if parts[i_id] in MISSING or parts[i_aal] in MISSING:
                    continue
                co = parse_co(parts[i_co])
                if co is None:
                    continue
                chrom, pos = co
                ral, aal = parts[i_ral], parts[i_aal]
                insert = insertion_sequence(ral, aal)
                if not insert:
                    continue
                yield InsertionCall(
                    chrom=chrom,
                    pos=pos,
                    record_pos=record_pos,
                    sample=sample,
                    svid=parts[i_id],
                    insert=insert,
                    declared_length=int(parts[i_ln]),
                )
