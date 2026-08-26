"""Strand- and phase-independent comparison of tandem-repeat motifs.

``GC`` and ``CG`` are the same repeat, and so are ``AAT``/``ATA``/``TAA`` and
their reverse complements ``ATT``/``TTA``/``TAT``. Motifs are reduced to their
primitive unit (``ATAT`` -> ``AT``) and then to the lexicographically smallest
rotation of that unit or of its reverse complement. Two motifs are equivalent
when those canonical forms agree; :func:`motif_distance` additionally scores
near-misses so a caller can accept ``N`` edits.

Nothing here knows about a particular repeat catalogue -- see
:mod:`novelty.platforms` for that.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_COMPLEMENT = str.maketrans("ACGTNacgtn", "TGCANtgcan")

# Rotational edit distance is O(len^2) per rotation and only meaningful for
# short units; longer motifs fall back to exact canonical comparison. Tunable
# per call -- raising it costs time, lowering it turns near misses into novelty.
MAX_FUZZY_MOTIF = 50


def reverse_complement(seq: str) -> str:
    """Reverse complement of a DNA string."""
    return seq.translate(_COMPLEMENT)[::-1]


def primitive_unit(seq: str) -> str:
    """Smallest ``u`` with ``u * k == seq``; ``ATAT`` -> ``AT``. O(len) via KMP."""
    n = len(seq)
    if n < 2:
        return seq
    fail = [0] * n
    k = 0
    for i in range(1, n):
        while k and seq[i] != seq[k]:
            k = fail[k - 1]
        if seq[i] == seq[k]:
            k += 1
        fail[i] = k
    period = n - fail[n - 1]
    return seq[:period] if n % period == 0 else seq


def least_rotation(seq: str) -> str:
    """Lexicographically smallest rotation of ``seq``. Booth's algorithm, O(len)."""
    n = len(seq)
    if n < 2:
        return seq
    doubled = seq + seq
    fail = [-1] * (2 * n)
    k = 0
    for j in range(1, 2 * n):
        cj = doubled[j]
        i = fail[j - k - 1]
        while i != -1 and cj != doubled[k + i + 1]:
            if cj < doubled[k + i + 1]:
                k = j - i - 1
            i = fail[i]
        if cj != doubled[k + i + 1]:
            if cj < doubled[k]:
                k = j
            fail[j - k] = -1
        else:
            fail[j - k] = i + 1
    return doubled[k:k + n]


def canonical_motif(motif: str, *, stranded: bool = False) -> str:
    """Strand- and phase-independent key for a repeat unit.

    ``GC`` and ``CG`` collapse to the same key, as do ``AAT`` and ``ATT``.
    Pass ``stranded=True`` to keep the reverse complement distinct.
    """
    unit = primitive_unit(motif.strip().upper())
    if not unit:
        return ""
    forward = least_rotation(unit)
    if stranded:
        return forward
    return min(forward, least_rotation(reverse_complement(unit)))


def canonical_motifs(values, *, stranded: bool = False) -> np.ndarray:
    """Vectorised :func:`canonical_motif` over an array-like of motif strings.

    Catalogues repeat their motifs heavily (hg38 ``simpleRepeat`` has 1.05M rows
    but only 516k distinct sequences), so each distinct string is canonicalised
    exactly once and the result is broadcast back through the factor codes.
    Returns an object-dtype array so motifs of different lengths are not padded.
    """
    series = pd.Series(values, dtype=object).fillna("")
    codes, uniques = pd.factorize(series, sort=False)
    if len(uniques) == 0:
        return np.empty(len(series), dtype=object)
    table = np.empty(len(uniques) + 1, dtype=object)
    table[:-1] = [canonical_motif(str(u), stranded=stranded) for u in uniques]
    table[-1] = ""                      # factorize marks missing values as -1
    return table[np.where(codes < 0, len(uniques), codes)]


def _edit_distance(a: str, b: str, cutoff: int) -> int:
    """Levenshtein distance, short-circuiting once it exceeds ``cutoff``."""
    if abs(len(a) - len(b)) > cutoff:
        return cutoff + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            val = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            cur.append(val)
            best = min(best, val)
        if best > cutoff:
            return cutoff + 1
        prev = cur
    return prev[-1]


def motif_distance(query: str, target: str, cutoff: int, *, stranded: bool = False,
                   max_fuzzy_motif: int = MAX_FUZZY_MOTIF) -> int:
    """Edit distance between two motifs, minimised over rotation and strand.

    Returns ``0`` for equivalent motifs and ``cutoff + 1`` when the two are
    further apart than ``cutoff`` (or longer than ``max_fuzzy_motif``, above
    which only exact canonical equality is tested).
    """
    qc = canonical_motif(query, stranded=stranded)
    tc = canonical_motif(target, stranded=stranded)
    if qc == tc:
        return 0
    if cutoff <= 0:
        return cutoff + 1
    if len(qc) > max_fuzzy_motif or len(tc) > max_fuzzy_motif:
        return cutoff + 1

    unit = primitive_unit(query.strip().upper())
    candidates = [unit[i:] + unit[:i] for i in range(len(unit))]
    if not stranded:
        rc = reverse_complement(unit)
        candidates += [rc[i:] + rc[:i] for i in range(len(rc))]

    best = cutoff + 1
    for cand in candidates:
        limit = min(cutoff, best - 1)
        if limit < 0:
            break
        dist = _edit_distance(cand, tc, limit)
        if dist <= limit:
            best = dist
            if best == 0:
                break
    return best
