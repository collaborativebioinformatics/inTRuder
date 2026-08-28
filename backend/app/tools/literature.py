"""The tool that reads the published literature, as opposed to our own data.

Three kinds of answer now exist in this agent, and they fail differently. The
registry answers from tables somebody curated. `describe_vcf` answers from a file
nobody has processed. This one answers from a third-party index of ~45 million
records, which means the failure mode is not "no answer" but "a confident answer
built on the wrong search" — Europe PMC returns a large, plausible, relevance
sorted result set for a query that has quietly gone wrong.

So the tool does not compose one query and trust it. It composes several framings
of the same question, runs them together, and scores each against the records it
returned; the model supplies the terms whose absence would prove a framing wrong.
See `app.util.europepmc` for the measurements behind that.
"""

from __future__ import annotations

from typing import Annotated, Literal

from langchain_core.tools import tool

from app.tools.payload import dump
from app.util.europepmc import EuropePmcError, search


@tool
async def search_literature(
    gene: Annotated[
        str | None,
        "Gene symbol to search for, e.g. 'RFC1'. The main anchor for a search; "
        "take it from a locus's gene annotation or from strchive_loci.gene.",
    ] = None,
    motif: Annotated[
        str | None,
        "Repeat motif to require in the title or abstract, e.g. 'AAGGG'. Narrows "
        "hard and is usually only worth it for well-studied loci.",
    ] = None,
    disease: Annotated[
        str | None,
        "Disease name, e.g. 'CANVAS'. Query strchive_loci for the real name of a "
        "disease locus rather than supplying one from memory.",
    ] = None,
    topic: Annotated[
        str | None,
        "Any other phrase that must appear in the title or abstract, e.g. "
        "'long-read sequencing'.",
    ] = None,
    must_mention: Annotated[
        list[str] | None,
        "Terms that MUST appear in a paper's title or abstract for it to count as "
        "on target. This is how you say what would prove the search wrong: for "
        "gene 'AR' pass ['androgen'], because 'AR' alone also matches augmented "
        "reality and every other use of the abbreviation. Results are scored "
        "against these and a framing that fails is discarded. Defaults to the "
        "gene symbol. Supply your own whenever the symbol is ambiguous.",
    ] = None,
    reject_mention: Annotated[
        list[str] | None,
        "Terms whose presence means a paper is off target, e.g. "
        "['augmented reality']. Optional.",
    ] = None,
    repeat_context: Annotated[
        bool,
        "Require repeat-biology context (repeat expansion / tandem repeat / "
        "microsatellite / VNTR). Leave true unless the question is deliberately "
        "about something else in the gene.",
    ] = True,
    sort: Annotated[
        Literal["relevance", "cited", "recent"],
        "'cited' for the landmark papers on a locus, 'recent' for what is new, "
        "'relevance' otherwise.",
    ] = "relevance",
    limit: Annotated[int, "Papers to return, 1-8."] = 5,
) -> str:
    """Search the published literature for a gene, locus, motif or disease.

    Use this for any question about what is *known* — what has been published on
    a gene, whether a repeat here is described anywhere, what a disease locus is
    associated with. It is the only source of citations: never cite a paper, a
    PMID, a DOI or an author from memory, and never state a finding as published
    unless it came back from this tool.

    Returns the papers of whichever query framing scored best, plus
    `strategies_tried` — every framing attempted, its hit count and what
    fraction of its results actually mentioned your terms. Several framings are
    run because a well-formed query can still be the wrong one: searching a gene
    symbol alone can return hundreds of thousands of papers whose top hits merely
    mention it in passing, and the hit count does not reveal that.

    Cite only what comes back, as a markdown link using each result's `url`, and
    do not assert a conclusion the returned `abstract_snippet` does not support.
    If `results` is empty, say that nothing was found — that is a real finding
    about the literature, and filling it in from memory is the one thing this
    tool exists to prevent.
    """
    try:
        report = await search(
            gene=gene,
            motif=motif,
            disease=disease,
            topic=topic,
            must_mention=must_mention,
            reject_mention=reject_mention,
            repeat_context=repeat_context,
            sort=sort,
            limit=limit,
        )
    except EuropePmcError as exc:
        return dump({"error": str(exc), "source": "Europe PMC"})
    return dump(report)
