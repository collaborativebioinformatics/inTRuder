"""Comparison of tandem-repeat motifs, up to a configurable notion of sameness.

Three separate things can make two motif strings the same repeat, and they are
independent knobs because they are not equally safe:

*period reduction* (always on)
    ``CAGCAG`` is not a 6bp repeat, it is a 3bp one written twice, so every
    motif is first reduced to its primitive unit. This is arithmetic, not a
    judgement call, and there is no flag for it.

*rotation* (:attr:`MotifEquivalence.circular`, on by default)
    ``CAG``, ``AGC`` and ``GCA`` are one repeat read from different starting
    phases. TRF picks that phase arbitrarily, and both sides of the comparison
    are TRF output, so a phase difference is an artefact of the caller rather
    than biology.

*reverse complement* (:attr:`MotifEquivalence.reverse_complement`, OFF by default)
    ``CAG`` and ``CTG`` are the same double-stranded repeat read from opposite
    strands. Whether that makes them the same *locus feature* is a judgement
    call -- for a CAG expansion it usually does, but it also collapses the
    homopolymers ``A`` and ``T``, which is rarely what you want. Off unless
    asked for, and :attr:`MotifEquivalence.reverse_complement_bp` can restrict
    it to motifs long enough for an RC match to mean something.

Two motifs are equivalent when their canonical forms agree under the policy in
force. Everything looser than that lives in :class:`MotifTolerance`, which is a
separate object on purpose: *equivalence* decides how the catalogue is keyed and
is baked into the index, while *tolerance* is a per-query judgement about how far
off a reference motif may be and still explain the locus. Tolerance has three
settings, and :meth:`MotifTolerance.compare` reports which one fired:

``max_edits``
    A flat edit budget at every motif length. ``0`` (the default) means nothing
    fuzzy happens at all and ``CAG`` never matches ``CAT``.

``max_edit_fraction``
    An edit budget proportional to motif length, applied only above
    :data:`STR_MAX_MOTIF`. This is the VNTR knob: two catalogues almost never
    agree on a 47bp consensus, but they agree to within a few percent of its
    length, and a flat budget cannot say that without also letting short motifs
    match each other.

``min_subrepeat_motif``
    Also accept a reference motif that the query motif *tiles*, so a query of
    ``ACC`` can match a reference consensus of ``ACCATC``. TRF reports one
    representative unit per locus and picks its period arbitrarily, so the two
    sides can describe one repeat at different periods.

Nothing here knows about a particular repeat catalogue -- see
:mod:`novelty.platforms` for that -- and nothing here needs numpy, so a
pure-stdlib step can compare motifs without taking on pandas. The vectorised
wrapper for catalogue-scale data is :func:`novelty.platforms.canonical_motifs`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

# Full IUPAC, not just ACGTN: a catalogue is entitled to write an ambiguous base
# in a consensus, and translating only ACGTN would *reverse* R/Y/S/W/K/M/B/D/H/V
# without complementing them, silently turning `ACRYN` into `NYRGT` instead of
# `NRYGT`. Same table as str-analysis `utils/misc_utils.COMPLEMENT`, plus the
# lowercase half so a soft-masked motif survives.
_COMPLEMENT = str.maketrans(
    "ACGTUNRYSWKMBDHVacgtunryswkmbdhv",
    "TGCAANYRSWMKVHDBtgcaanyrswmkvhdb",
)

# Rotational edit distance is O(len^2) per rotation and only meaningful for
# short units; longer motifs fall back to exact canonical comparison. Tunable
# per call -- raising it costs time, lowering it turns near misses into novelty.
# It has to clear the VNTR range to be useful: two catalogues rarely agree on a
# long consensus, which is exactly where a near miss is the interesting answer.
MAX_FUZZY_MOTIF = 200

# The motif length that separates an STR from a VNTR. At or below it the exact
# sequence of the unit is reliable and a single substitution is a real
# difference -- CAG and CAT are not the same repeat. Above it, callers and
# assemblies routinely disagree on the consensus, so exact equality is the wrong
# test. str-analysis draws the same line at 6bp: `utils/eh_catalog_utils.py`
# `compute_repeat_unit_id` keys motifs <= 6bp by sequence and longer ones by
# length alone, and `merge_loci.py` exposes that as
# --motif-length-match-sufficient-for-VNTRs.
STR_MAX_MOTIF = 6


@dataclass(frozen=True)
class MotifEquivalence:
    """Which transformations of a repeat unit still count as the same repeat.

    Period reduction (``CAGCAG`` -> ``CAG``) is not listed because it is always
    applied. The two that are listed differ in how safe they are, which is why
    they default differently:

    ``circular``
        Treat every rotation of the unit as the same repeat, so ``CAG``, ``AGC``
        and ``GCA`` agree. On by default -- TRF chooses the starting phase
        arbitrarily on both sides of the comparison.

    ``reverse_complement``
        Additionally treat the unit's reverse complement as the same repeat, so
        ``CAG`` and ``CTG`` agree. **Off by default**: it also merges the
        homopolymers ``A`` and ``T``, which loses a real distinction.

        Note that ``GC``/``CG`` and ``AT``/``TA`` are *not* examples of this --
        they are rotations of one another and collapse under ``circular``.

    ``reverse_complement_bp``
        Only consider the reverse complement for units at least this long, so
        the short motifs where an RC match is most likely coincidental keep
        their strands apart. ``None`` (the default) applies it at every length.
        It does nothing at all unless ``reverse_complement`` is set.
    """

    circular: bool = True
    reverse_complement: bool = False
    reverse_complement_bp: int | None = None

    def rc_applies(self, unit: str) -> bool:
        """Whether the reverse complement of this primitive unit is in scope."""
        if not self.reverse_complement:
            return False
        if self.reverse_complement_bp is None:
            return True
        return len(unit) >= self.reverse_complement_bp

    def describe(self) -> str:
        """One line naming the policy, for `query` output and log messages."""
        parts = ["period reduction"]
        if self.circular:
            parts.append("rotation")
        if self.reverse_complement:
            limit = self.reverse_complement_bp
            parts.append("reverse complement"
                         + (f" (>={limit}bp only)" if limit is not None else ""))
        return " + ".join(parts)


# What the tool does unless told otherwise: phase-independent, strand-aware.
DEFAULT_EQUIVALENCE = MotifEquivalence()


def reverse_complement(seq: str) -> str:
    """Reverse complement of a DNA string."""
    return seq.translate(_COMPLEMENT)[::-1]


def primitive_unit(seq: str) -> str:
    """Smallest ``u`` with ``u * k == seq``; ``CAGCAG`` -> ``CAG``. O(len) via KMP."""
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


def canonical_motif(motif: str,
                    equivalence: MotifEquivalence = DEFAULT_EQUIVALENCE) -> str:
    """Key under which two motifs are the same repeat, given an equivalence policy.

    Always reduces to the primitive unit; then folds in rotation and reverse
    complement as ``equivalence`` allows. Two motifs are the same repeat exactly
    when this returns the same string for both.

    The key is a pure function of the motif and the policy, which is what lets
    the catalogue intern it (see :class:`novelty.catalog.RepeatCatalog`). Note
    that ``reverse_complement_bp`` keys off the unit length, and reverse
    complementing preserves length, so a pair of RC-equivalent motifs is always
    on the same side of that threshold.
    """
    unit = primitive_unit(motif.strip().upper())
    if not unit:
        return ""
    forward = least_rotation(unit) if equivalence.circular else unit
    if not equivalence.rc_applies(unit):
        return forward
    rc = reverse_complement(unit)
    return min(forward, least_rotation(rc) if equivalence.circular else rc)


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


def motif_distance(query: str, target: str, cutoff: int,
                   equivalence: MotifEquivalence = DEFAULT_EQUIVALENCE, *,
                   max_fuzzy_motif: int = MAX_FUZZY_MOTIF) -> int:
    """Edit distance between two motifs, minimised over whatever ``equivalence`` allows.

    Returns ``0`` for equivalent motifs and ``cutoff + 1`` when the two are
    further apart than ``cutoff`` (or longer than ``max_fuzzy_motif``, above
    which only exact canonical equality is tested).

    ``cutoff <= 0`` is the important case: it returns before any edit distance is
    computed, so a one-substitution near miss like ``CAG`` against ``CAT`` is
    *not* a match. Only a caller that has explicitly asked for fuzziness by
    raising ``--max-motif-edits`` ever sees one.
    """
    qc = canonical_motif(query, equivalence)
    tc = canonical_motif(target, equivalence)
    if qc == tc:
        return 0
    if cutoff <= 0:
        return cutoff + 1
    if len(qc) > max_fuzzy_motif or len(tc) > max_fuzzy_motif:
        return cutoff + 1
    # Every candidate below is a rotation of the query's primitive unit, and
    # rotation preserves length, so a length gap wider than the cutoff rules them
    # all out at once -- worth checking before building the rotation list.
    if abs(len(qc) - len(tc)) > cutoff:
        return cutoff + 1

    # Rotations and the reverse complement are folded into the candidate set only
    # when the policy admits them, so fuzziness can never smuggle in a match that
    # exact comparison would have rejected on strand or phase grounds.
    unit = primitive_unit(query.strip().upper())
    candidates = ([unit[i:] + unit[:i] for i in range(len(unit))]
                  if equivalence.circular else [unit])
    if equivalence.rc_applies(unit):
        rc = reverse_complement(unit)
        candidates += ([rc[i:] + rc[:i] for i in range(len(rc))]
                       if equivalence.circular else [rc])

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


# --------------------------------------------------------------------------- #
# tolerance: how far off a motif may be and still explain the same repeat
# --------------------------------------------------------------------------- #

# Which rule accepted a pair of motifs, reported alongside every verdict so a
# loosened match never looks like an exact one in the output.
MATCH_EXACT = "exact"          # same canonical form
MATCH_FUZZY = "fuzzy"          # within the flat --max-motif-edits budget
MATCH_VNTR = "vntr"            # within the proportional budget, VNTR lengths only
MATCH_SUBREPEAT = "subrepeat"  # one motif tiles the other
MATCH_NONE = ""                # not the same repeat under this tolerance

MATCH_KINDS = (MATCH_EXACT, MATCH_FUZZY, MATCH_VNTR, MATCH_SUBREPEAT)


class MotifMatch(NamedTuple):
    """Whether two motifs are the same repeat, and on what grounds."""

    kind: str     # one of MATCH_KINDS, or MATCH_NONE
    edits: int    # 0 for an exact match; budget + 1 when nothing matched

    @property
    def matched(self) -> bool:
        return self.kind != MATCH_NONE


def edit_budget(a: str, b: str, max_edits: int,
                max_edit_fraction: float | None = None, *,
                str_max_motif: int = STR_MAX_MOTIF) -> int:
    """How many edits are allowed between two canonical motifs.

    The flat ``max_edits`` applies at every length. ``max_edit_fraction`` adds a
    budget proportional to the longer motif, but only above ``str_max_motif``:
    below that a substitution is a real difference between two STRs, and scaling
    the budget with length would be scaling it with noise. The two combine by
    taking whichever is larger, so raising one never tightens the other.
    """
    budget = max(int(max_edits), 0)
    if max_edit_fraction:
        longest = max(len(a), len(b))
        if longest > str_max_motif:
            budget = max(budget, int(longest * max_edit_fraction))
    return budget


def tiling_distance(unit: str, target: str, cutoff: int) -> int:
    """Mismatches between ``target`` and ``unit`` tiled across it, best phase wins.

    ``unit`` is repeated (with a partial copy at the end if it does not divide
    evenly) to the length of ``target``, and the two are compared base for base;
    the phase of ``unit`` that matches best is the one that counts. Returns
    ``cutoff + 1`` once the best phase is known to be worse than ``cutoff``.

    This is the motif-string form of the reference-sequence purity test in
    str-analysis `utils/find_motif_utils.py` ``compute_repeat_purity``, which
    tiles a motif over real sequence and counts matching bases. Here the target
    is another catalogue's consensus rather than the reference itself, which is
    weaker evidence but needs no FASTA.

    At least two whole copies of ``unit`` must fit, otherwise it is not tiling
    anything and any short unit would "explain" any long motif.
    """
    n = len(target)
    if not unit or len(unit) * 2 > n:
        return cutoff + 1
    best = cutoff + 1
    for phase in range(len(unit)):
        rotated = unit[phase:] + unit[:phase]
        tiled = (rotated * (n // len(rotated) + 1))[:n]
        distance = 0
        for x, y in zip(tiled, target):
            if x != y:
                distance += 1
                if distance >= best:
                    break
        else:
            best = distance
            if best == 0:
                break
    return best


@dataclass(frozen=True)
class MotifTolerance:
    """How far off a reference motif may be and still count as the same repeat.

    Distinct from :class:`MotifEquivalence`, which decides what makes two motifs
    the *same string* and is baked into the catalogue index. Tolerance is decided
    per query and can be swept without rebuilding anything.

    ``max_edits``
        Flat edit budget at every motif length. ``0`` (the default) means exact
        canonical matching only.

    ``max_edit_fraction``
        Edit budget as a fraction of the longer motif, above
        :data:`STR_MAX_MOTIF` only. ``None`` disables it.

    ``min_subrepeat_motif``
        Also accept a motif that tiles the other, when the tiling unit is at
        least this long. ``None`` disables it. It shares the edit budget above,
        so with both budgets at zero it only accepts a tiling that is exact --
        and an exact tiling is already handled by period reduction, so this
        setting does nothing on its own.

    ``max_fuzzy_motif``
        Longest motif any of the above is attempted on; beyond it only exact
        canonical equality is tested, because the search is superlinear in motif
        length.
    """

    max_edits: int = 0
    max_edit_fraction: float | None = None
    min_subrepeat_motif: int | None = None
    max_fuzzy_motif: int = MAX_FUZZY_MOTIF

    def __bool__(self) -> bool:
        """Whether anything looser than exact canonical equality is enabled."""
        return bool(self.max_edits or self.max_edit_fraction
                    or self.min_subrepeat_motif is not None)

    def describe(self) -> str:
        """One line naming the tolerance, for `query` output and log messages."""
        if not self:
            return "exact canonical match only"
        parts = []
        if self.max_edits:
            parts.append(f"<={self.max_edits} edit(s)")
        if self.max_edit_fraction:
            parts.append(f"<={self.max_edit_fraction:g} x motif length "
                         f"(>{STR_MAX_MOTIF}bp motifs only)")
        if self.min_subrepeat_motif is not None:
            parts.append(f"tiling by a motif >={self.min_subrepeat_motif}bp")
        return " or ".join(parts)

    def compare(self, query: str, target: str,
                equivalence: MotifEquivalence = DEFAULT_EQUIVALENCE, *,
                query_canonical: str | None = None,
                target_canonical: str | None = None) -> MotifMatch:
        """Whether these two motifs are the same repeat, and by which rule.

        ``query_canonical`` / ``target_canonical`` are an optimisation for
        callers that already hold them -- :class:`novelty.catalog.RepeatCatalog`
        interns the catalogue side, so re-deriving it per candidate would be the
        dominant cost of screening.
        """
        qc = (canonical_motif(query, equivalence) if query_canonical is None
              else query_canonical)
        tc = (canonical_motif(target, equivalence) if target_canonical is None
              else target_canonical)
        if qc == tc:
            return MotifMatch(MATCH_EXACT, 0)

        budget = edit_budget(qc, tc, self.max_edits, self.max_edit_fraction)
        if budget > 0:
            distance = motif_distance(query, target, budget, equivalence,
                                      max_fuzzy_motif=self.max_fuzzy_motif)
            if distance <= budget:
                # Name the tighter rule when both would have accepted it, so the
                # output does not blame the VNTR budget for an ordinary near miss.
                kind = MATCH_FUZZY if distance <= self.max_edits else MATCH_VNTR
                return MotifMatch(kind, distance)

        if self.min_subrepeat_motif is not None:
            unit, whole = (qc, tc) if len(qc) <= len(tc) else (tc, qc)
            if (len(unit) >= self.min_subrepeat_motif
                    and len(whole) <= self.max_fuzzy_motif):
                # The budget is measured against the tiled length, since that is
                # how many bases the claim is actually made about.
                sub_budget = max(budget, edit_budget(whole, whole, self.max_edits,
                                                     self.max_edit_fraction))
                distance = tiling_distance(unit, whole, sub_budget)
                if distance <= sub_budget:
                    return MotifMatch(MATCH_SUBREPEAT, distance)

        return MotifMatch(MATCH_NONE, budget + 1)


# What the tool does unless told otherwise: nothing fuzzy at all.
DEFAULT_TOLERANCE = MotifTolerance()
