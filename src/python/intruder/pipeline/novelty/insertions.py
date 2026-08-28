"""Purity of the SV insertions themselves, and the filters built on it.

Two different things get called purity, and both matter:

*per repeat call*
    ``purity`` in the ``sv_trfcaller.py`` table -- Tandem Repeat Finder's percent
    identity between the perfect repeat and the sequence it actually found, i.e.
    how repetitive that one tandem repeat is.

*per insertion*
    what fraction of the whole inserted sequence is tandem repeat at all. An
    insertion whose repeats cover 30% of it is mostly something else, and
    calling that locus a novel TR is a stretch.

The second is computed here as ``union(rep_start, rep_end) / insert_size`` over
all the TRF calls belonging to one insertion. The union matters: TRF happily
reports overlapping calls for the same stretch of sequence (one insertion in the
sample data carries 64 of them), so adding up ``rep_length`` double-counts bases
and can push "purity" well past 1.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

import numpy as np
import pandas as pd

PASS = "PASS"


class Check(NamedTuple):
    """One threshold on one column. ``None`` on either side means no bound."""

    column: str
    tag: str
    minimum: float | None = None
    maximum: float | None = None

    @property
    def active(self) -> bool:
        return self.minimum is not None or self.maximum is not None


def parse_sizes(values) -> pd.Series:
    """Coerce an insert-size column to integers.

    ``sv_trfcaller.py`` writes the VCF ``LEN`` field straight through, so the
    column reads ``[415]`` rather than ``415``; the first integer in the field is
    that sample's insertion length.
    """
    raw = pd.Series(values).astype("string")
    numeric = pd.to_numeric(raw, errors="coerce").astype("Float64")
    unparsed = numeric.isna()
    if unparsed.any():
        first = raw[unparsed].str.extract(r"(-?\d+)", expand=False)
        numeric[unparsed] = pd.to_numeric(first, errors="coerce").astype("Float64")
    return numeric.abs().astype("Int64")


def union_length(frame: pd.DataFrame, keys: Sequence[str], start_col: str,
                 end_col: str) -> pd.Series:
    """Bases covered by the union of ``[start, end)`` intervals within each group.

    Sorting by ``(keys, start)`` makes this a single sweep: a running maximum of
    the ends seen so far in the group is where the next interval's contribution
    begins, which handles both overlapping and fully nested calls.
    """
    keys = list(keys)
    ordered = frame.sort_values(keys + [start_col, end_col], kind="stable")
    start = ordered[start_col].to_numpy(dtype=np.int64)
    end = ordered[end_col].to_numpy(dtype=np.int64)

    running = ordered.groupby(keys, sort=False)[end_col].cummax().to_numpy(np.int64)
    previous = np.empty_like(running)
    previous[:1] = 0
    previous[1:] = running[:-1]
    first_of_group = ~ordered.duplicated(keys).to_numpy()

    lower = np.where(first_of_group, start, np.maximum(start, previous))
    covered = pd.Series(np.maximum(end - lower, 0), index=ordered.index)
    totals = covered.groupby([ordered[k] for k in keys], sort=False).transform("sum")
    return totals.reindex(frame.index)


def add_insertion_purity(frame: pd.DataFrame, *, keys: Sequence[str],
                         start_col: str = "rep_start", end_col: str = "rep_end",
                         size_col: str = "insert_size") -> pd.DataFrame:
    """Add ``insertion_repeat_bases`` and ``insertion_purity`` to ``frame``."""
    missing = [c for c in (*keys, start_col, end_col, size_col)
               if c not in frame.columns]
    if missing:
        raise KeyError(f"cannot compute insertion purity: missing column(s) {missing}")

    out = frame.copy()
    bases = union_length(out, keys, start_col, end_col)
    size = parse_sizes(out[size_col])
    out["insertion_repeat_bases"] = bases.astype("Int64")
    purity = bases.astype("Float64") / size.astype("Float64")
    # TRF can call a repeat that runs past the reported insert size; cap at 1 so
    # the column stays a fraction, but leave a missing size missing.
    out["insertion_purity"] = purity.clip(upper=1.0).round(3)
    return out


def filter_reasons(frame: pd.DataFrame, checks: Sequence[Check]) -> pd.Series:
    """A ``PASS``/reason column for a set of :class:`Check` thresholds.

    A row fails a check when its value falls outside the bounds; a missing value
    is not evidence of failure and passes. Reasons accumulate, comma separated.
    """
    tags = np.full(len(frame), "", dtype=object)
    for check in checks:
        check = Check(*check)
        if not check.active:
            continue
        if check.column not in frame.columns:
            raise KeyError(f"cannot filter on {check.column!r}: column not in table")
        values = pd.to_numeric(frame[check.column], errors="coerce")
        failed = np.zeros(len(frame), dtype=bool)
        if check.minimum is not None:
            failed |= (values < check.minimum).fillna(False).to_numpy()
        if check.maximum is not None:
            failed |= (values > check.maximum).fillna(False).to_numpy()
        tags = np.where(failed, np.where(tags == "", check.tag, tags + "," + check.tag),
                        tags)
    return pd.Series(np.where(tags == "", PASS, tags), index=frame.index, dtype=object)
