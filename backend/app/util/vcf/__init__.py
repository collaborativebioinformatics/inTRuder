"""What a VCF actually is, read out of the file rather than assumed.

Every downstream step in this project starts by pulling an inserted sequence and
a breakpoint out of a VCF, and where those live is a property of the *dialect*,
not of the format. A single-sample Sniffles record carries the whole insertion in
``ALT``. A SURVIVOR-merged record carries one representative allele in ``ALT``
and the per-sample truth in ``FORMAT/AAL`` -- minus its ``FORMAT/RAL`` anchor --
at the breakpoint in ``FORMAT/CO``. Reading the merged file the single-sample way
fails silently: you still get sequence, it is just the wrong sequence, at a
coordinate that is off by a median of 34 bp in this cohort's callset.

So this package reports before anything extracts, and it prefers observation to
assertion:

* Field roles -- which key holds sequence, length, coordinates, the originating
  caller's ID -- are inferred from the header's declared type and description
  *and* confirmed against the values actually present in the file (`dialect`).
* The example records are extracted twice, once record-level and once
  per-sample, with the disagreements between the two named and measured
  (`scan`). The difference is visible rather than claimed.

Deliberately pure Python: no cyvcf2, no htslib. A VCF header and its columns are
text, this only ever reads forwards, and the backend does not otherwise carry a
compiled bioinformatics dependency (the pipeline under ``src/python`` does, and
is a separate environment on purpose). The cost is that BCF -- the binary
encoding of the same content -- is refused rather than parsed.

    | module      | role                                              |
    |-------------|---------------------------------------------------|
    | `common`    | limits, patterns, the error type                  |
    | `paths`     | finding and opening files, confined to a root     |
    | `header`    | the `##` declarations                             |
    | `dialect`   | which field plays which role, and on what evidence|
    | `scan`      | the records, each read both ways                  |
    | `report`    | the sections, and the verdict in sentences        |
"""

from app.util.vcf.common import DEFAULT_MAX_RECORDS, VCF_SUFFIXES, VcfScanError
from app.util.vcf.paths import list_vcfs, resolve_vcf_path
from app.util.vcf.scan import scan_vcf

__all__ = [
    "DEFAULT_MAX_RECORDS",
    "VCF_SUFFIXES",
    "VcfScanError",
    "list_vcfs",
    "resolve_vcf_path",
    "scan_vcf",
]
