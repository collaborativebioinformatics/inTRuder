"""Building the sequence windows that get fed to Evo 2, and naming the token
spans inside them.

An Evo 2 forward pass returns one embedding vector *per token*, so a single pass
over a window yields as many pooled views as we care to slice out of it. That is
the whole reason this module exists: choosing what to embed is not a fork in the
road, it is a choice of which spans to pool, and they are all available at once.

The five spans, for an insertion placed after ``ins_coord``::

    [------ left flank ------][====== insertion ======][----- right flank -----]
     <-------- left -------->                           <------- right ------->
                     <-- junction_5p -->      <-- junction_3p -->
                              <-------- repeat ------->

They answer different questions, and the difference matters:

``repeat``
    pools over the TRF call itself. Dominated by motif composition, so it mostly
    re-derives what ``sv_trfcaller.py`` already reports. Useful as a control.
``left`` / ``right``
    genomic context, insertion excluded. Says where in the genome this is, not
    what was inserted.
``junction_5p`` / ``junction_3p``
    straddle the breakpoints. This is where novelty actually lives -- a novel TR
    is not unusual *as sequence* (Evo 2 trained on plenty of tandem repeats), it
    is unusual in being *placed here*. Only these two spans see both sides.

A window with ``insert=""`` is the reference allele at the same locus, which is
what the background comparison set is built from: identical construction, so the
only difference between a novel-TR window and its background is the insertion.

Coordinates
-----------
``ins_coord`` is the VCF ``POS`` of the anchor base, 1-based, and the insertion
sits immediately *after* it -- the same convention ``novelty`` reads. Used
directly as a 0-based slice boundary it splits the reference exactly there::

    left  = ref[ins_coord - flank : ins_coord]   # ends on the anchor base
    right = ref[ins_coord : ins_coord + flank]   # starts just past it

so no +/-1 correction appears anywhere below. ``rep_start``/``rep_end`` are
offsets *within the inserted sequence* (0-based, half-open), as
``sv_trfcaller.py`` writes them -- not genome coordinates.
"""

from __future__ import annotations

from typing import NamedTuple

from evo.utils.reference import Reference

# Segment names, in 5'->3' order. Exported so the extractor and the analysis
# side agree on one vocabulary rather than passing bare strings around.
SEGMENTS = ("left", "junction_5p", "repeat", "junction_3p", "right")


class Span(NamedTuple):
    """Half-open token span within a window, plus whether it was truncated."""

    start: int
    end: int
    complete: bool = True

    def __len__(self) -> int:
        return self.end - self.start


class WindowSpec(NamedTuple):
    """How to cut a window. One of these defines an embedding "method"."""

    flank: int = 3584
    """Reference bases taken on each side of the breakpoint.

    3584 is not arbitrary: ``2*3584 + 1024`` is exactly 8192, the context of the
    ``evo2_*_base`` checkpoints (and of Arc's own ``exon_classifier``). At the
    obvious-looking 4096 the longest windows reach 9216 and silently overflow.
    Raise it only against a long-context checkpoint.
    """

    junction: int = 64
    """Bases either side of a breakpoint that make up a junction span."""

    repeat_crop: int | None = 1024
    """Cap on inserted bases kept. ``None`` keeps the whole insertion.

    Insertions here run from 5 bp to 54 kb. Without a cap the ``repeat`` span is
    incomparable between rows and the window length varies by four orders of
    magnitude; with one, every window is at most ``2*flank + repeat_crop``. The
    crop is centred, so a long insertion contributes its middle rather than an
    arbitrary end.
    """

    @property
    def max_length(self) -> int:
        crop = self.repeat_crop if self.repeat_crop is not None else 0
        return 2 * self.flank + crop


DEFAULT_SPEC = WindowSpec()
"""The spec used when a caller does not pass one. 4 kb flanks sit well inside
Evo 2's 8 kb base-model context once the insertion is added."""


class Window(NamedTuple):
    """A built window: the sequence to tokenize, and where to pool from."""

    chrom: str
    ins_coord: int
    sequence: str
    segments: dict[str, Span]
    insert_length: int
    """Length of the insertion *before* cropping, kept as a covariate.

    Clusters in embedding space can be driven by insertion length alone; keeping
    the pre-crop length alongside the vectors is what lets that be checked
    rather than assumed away.
    """

    cropped: bool

    n_fraction: float = 0.0
    """Fraction of the window that is ``N``.

    Windows near an assembly gap are mostly padding: 112 of the 6127 windows in
    the sample callset exceed 10% N, all of them within a few hundred bases of
    chr1's telomeric N block, with left flanks around 42% N. Their embeddings
    describe the gap, not the locus, so the extractor uses this to drop or flag
    them rather than discovering the problem downstream in a cluster plot.
    """


def _clip(span: Span, lo: int, hi: int) -> Span:
    start, end = max(span.start, lo), min(span.end, hi)
    if end <= start:
        return Span(start, start, complete=False)
    return Span(start, end, complete=span.complete and (start, end) == span[:2])


def build_window(
    reference: Reference,
    chrom: str,
    ins_coord: int,
    insert: str = "",
    spec: WindowSpec = DEFAULT_SPEC,
    rep_start: int | None = None,
    rep_end: int | None = None,
) -> Window:
    """Build one window and its segment spans.

    ``insert=""`` gives the reference allele at this locus -- same flanks, no
    insertion -- which is how background windows are made. The two junction
    spans then coincide and ``repeat`` is empty.

    ``rep_start``/``rep_end`` place the ``repeat`` span on one TRF call within
    the insertion. Omitted, it covers the whole (cropped) insertion. Passing
    them matters when an insertion carries several TRF calls, since otherwise
    every call from that insertion would pool an identical ``repeat`` vector.
    """
    if ins_coord < 0:
        raise ValueError(f"ins_coord must be non-negative, got {ins_coord}")

    insert_length = len(insert)
    kept, offset = _crop(insert, spec.repeat_crop)

    left_seq = reference.fetch(chrom, max(0, ins_coord - spec.flank), ins_coord)
    right_seq = reference.fetch(chrom, ins_coord, ins_coord + spec.flank)
    sequence = left_seq + kept + right_seq

    # Breakpoints in window coordinates.
    bp5 = len(left_seq)
    bp3 = bp5 + len(kept)
    end = len(sequence)

    if rep_start is None or rep_end is None:
        rep = Span(bp5, bp3, complete=len(kept) == insert_length)
    else:
        # rep_start/rep_end index the uncropped insertion; shift into the window.
        rep = _clip(
            Span(bp5 + rep_start - offset, bp5 + rep_end - offset), bp5, bp3
        )

    # A flank near a contig edge comes back short from `fetch`, so its span is
    # already exactly the sequence and `_clip` has nothing to trim. Completeness
    # has to be judged against what was *asked* for, not against the window.
    segments = {
        "left": Span(0, bp5, complete=len(left_seq) == spec.flank),
        "junction_5p": _clip(Span(bp5 - spec.junction, bp5 + spec.junction), 0, end),
        "repeat": rep,
        "junction_3p": _clip(Span(bp3 - spec.junction, bp3 + spec.junction), 0, end),
        "right": Span(bp3, end, complete=len(right_seq) == spec.flank),
    }
    return Window(
        chrom=chrom,
        ins_coord=ins_coord,
        sequence=sequence,
        segments=segments,
        insert_length=insert_length,
        cropped=len(kept) != insert_length,
        n_fraction=sequence.count("N") / len(sequence) if sequence else 0.0,
    )


def _crop(insert: str, limit: int | None) -> tuple[str, int]:
    """Centre-crop ``insert`` to ``limit`` bases. Returns the kept text and the
    offset of its first base within the original insertion."""
    if limit is None or len(insert) <= limit:
        return insert, 0
    offset = (len(insert) - limit) // 2
    return insert[offset : offset + limit], offset
