"""The tool that maps free-text clinical language to genes, via validated HPO terms.

See `app.util.hpo_pipeline` for the 6-step pipeline this wraps - it lives beside
`app.util.europepmc` rather than under `app.agent` for the same reason: it is
logic a tool wraps, not part of the agent graph, and `app.agent`'s own package
init imports the graph, which imports `app.tools` - putting the pipeline under
`app.agent` would make this module's import a cycle.

This module exposes one tool rather than one per step, the same choice
`search_literature` makes: the agent gets a structured result with full
breadcrumbs (what was tried, what was rejected and why, what was validated), not
five separate tool calls to orchestrate by hand.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from app.tools.payload import dump
from app.util.hpo_pipeline import DEFAULT_SIMILARITY_THRESHOLD, phenotype_to_genes


@tool
def resolve_phenotype(
    description: Annotated[
        str,
        "Free-text clinical description, no patient identifiers, e.g. "
        "'progressive scoliosis and sensorineural hearing loss'.",
    ],
    max_candidates: Annotated[
        int, "How many nearest HPO terms to consider before validation, 1-10."
    ] = 5,
) -> str:
    """Map a free-text phenotype description to real HPO terms and the genes they implicate.

    Use this whenever the user describes a phenotype in plain clinical language
    rather than naming an HPO id or a gene directly. It does five things in one
    call: embeds the text, finds the nearest HPO terms by similarity, validates
    each one against the live HPO ontology, looks up each validated term's
    parent/child terms for context, and joins the validated term(s) against the
    official HPO gene-phenotype release to get implicated genes.

    Read the response like this:
    - `validated_terms` are the ONLY terms that passed a real existence check
      against current HPO data. `genes` is built from these and only these.
    - `rejected` lists every candidate that did not pass, and why - either it
      scored too low to trust, or the id it produced does not exist / is
      obsolete. An empty `validated_terms` with a non-empty `rejected` means
      nothing in the description matched a real HPO concept confidently enough
      - say that plainly rather than guessing a term from memory.
    - `related_terms` (parents/children of each validated term) is informational
      context only. It is NOT part of how `genes` was computed - do not treat a
      related term as if it were validated, and do not use it to justify a gene
      that is not already in `genes`.
    - A high similarity score is not a guarantee of the right concept: a
      confidently-scored match can still be the wrong term (e.g. an antonym or
      an adjacent-but-different concept), because this uses a general-purpose
      text embedding, not a clinical one. Sanity-check `validated_terms[].name`
      against what the user actually described before treating the gene list as
      settled, and say so if a name looks like an odd fit for the description.

    Once you have a `genes` list, call `set_view(genes=[...])` to show the
    cohort's candidate repeats in those genes, and say in prose what phenotype
    and HPO term(s) that gene list came from.
    """
    max_candidates = max(1, min(max_candidates, 10))
    result = phenotype_to_genes(description, k=max_candidates, threshold=DEFAULT_SIMILARITY_THRESHOLD)
    return dump(result)
