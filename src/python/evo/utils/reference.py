"""Reference sequence access.

Kept behind a two-method protocol so window construction never learns which
FASTA library is installed: the tests hand it a dict of strings, the cluster run
hands it pyfaidx, and neither knows about the other.

Soft masking
------------
The UCSC hg38 FASTA is soft-masked -- repetitive sequence is written in
lowercase, which is precisely the sequence this project cares about. Evo 2's
tokenizer is byte-level, so ``a`` and ``A`` are *different tokens*, and a
soft-masked tandem repeat would tokenize differently from the same repeat read
out of a VCF ALT field. Every reader here upper-cases on the way out; do not
remove that without checking what the tokenizer does with lowercase.
"""

from __future__ import annotations

from typing import Protocol


class Reference(Protocol):
    """Anything that can hand back reference sequence for a contig slice."""

    def fetch(self, chrom: str, start: int, end: int) -> str:
        """Return ``[start, end)`` 0-based, upper-cased.

        Requests running off either end of the contig are **clipped, not
        padded**, so the caller gets a short string rather than one containing
        invented bases. Window building relies on this to mark truncated spans
        instead of embedding padding as if it were sequence.
        """


class DictReference:
    """In-memory reference over ``{chrom: sequence}``. For tests and small runs."""

    def __init__(self, sequences: dict[str, str]):
        self._seqs = {k: v.upper() for k, v in sequences.items()}

    def fetch(self, chrom: str, start: int, end: int) -> str:
        try:
            seq = self._seqs[chrom]
        except KeyError:
            raise KeyError(f"contig {chrom!r} not in reference") from None
        return seq[max(0, start) : max(0, end)]

    @property
    def contigs(self) -> list[str]:
        return sorted(self._seqs)


class FastaReference:
    """Indexed FASTA via pyfaidx. Requires a ``.fai`` beside the file."""

    def __init__(self, path: str):
        try:
            import pyfaidx
        except ImportError:  # pragma: no cover - exercised only on the cluster
            raise ImportError(
                "FastaReference needs pyfaidx, a default dependency of this "
                "project -- run `uv sync`. (It used to live in the 'embed' "
                "extra, which broke `evo-embed --dry-run` on a default sync.)"
            ) from None
        # as_raw returns str rather than a Sequence object, so slicing is cheap.
        self._fa = pyfaidx.Fasta(path, as_raw=True, sequence_always_upper=True)

    def fetch(self, chrom: str, start: int, end: int) -> str:
        try:
            contig = self._fa[chrom]
        except KeyError:
            raise KeyError(f"contig {chrom!r} not in reference") from None
        # pyfaidx clips at contig bounds; guard the low end ourselves.
        return str(contig[max(0, start) : max(0, end)])

    @property
    def contigs(self) -> list[str]:
        return sorted(self._fa.keys())
