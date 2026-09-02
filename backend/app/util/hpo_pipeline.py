"""Phenotype-to-loci: free-text clinical description in, candidate genes out.

Implements the 6-step pipeline from the phenotype-to-loci spec. Each step is its
own function so it can be tested and inspected independently — see
`backend/tests/test_hpo_pipeline.py`. `phenotype_to_genes` is the orchestrator
`app.tools.hpo.resolve_phenotype` calls; the individual steps are not exposed as
separate tools, the same way `search_literature` runs several query framings
internally rather than exposing each as its own tool.

Step 1 (embed free text) and Step 2A (build the HPO term index) use the same
`sentence-transformers` model, `all-mpnet-base-v2` — general-purpose, not
clinical-specific, per the spec's explicit choice; the model must match between
query and index or cosine similarity is meaningless. Step 2A is a one-time
script (`scripts/build_hpo_index.py`), not something the request path runs.

Step 3, `resolve_hpo()`, is the one hard guardrail: it is a pure existence check
against `PyHPO`'s `Ontology` (is this id real, and not obsolete?), never a
semantic judgement, and a candidate that fails it is dropped before it can reach
Step 4, Step 5, or the UI — see its docstring for why this has to be a separate
step from Step 2B's similarity search.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np
from pyhpo import Ontology

from app.config import settings

_INDEX_PATH = settings.registry_dir / "hpo" / "term_index.npz"
_HPO_ID_RE = re.compile(r"^HP:\d{7}$")

#: Step 2B similarity threshold, chosen empirically per the spec's floor/ceiling
#: method (see `backend/tests/test_hpo_pipeline.py::test_threshold_calibration`
#: for the exact phrases and to reproduce). Five nonsense phrases ("purple
#: elephant riding a bicycle", "the stock market closed higher today", ...)
#: scored 0.194-0.486 best-match against this index (all-mpnet-base-v2, this
#: index); five phrases with an obvious correct HPO concept ("seizures",
#: "hearing loss", "short stature", "intellectual disability", "curved spine")
#: scored 0.709-0.754. The gap [0.486, 0.709] does not overlap, so a fixed
#: cutoff placed near its middle is reliable enough for the prototype. Revisit
#: as real free-text input accumulates - the spec calls this out explicitly.
#:
#: One of those five "obvious" phrases is a real caution, not just a data
#: point: "curved spine" (the spec's own worked example, expected to match
#: Scoliosis) actually matches "Abnormally straight spine" top-1, and Scoliosis
#: does not appear even in the top 8 candidates. The score is high (0.726) and
#: clears this threshold easily, so resolve_hpo() validates it, and the
#: pipeline would confidently return genes for a term that is arguably the
#: opposite of what was asked. The threshold catches nonsense; it does not
#: catch a confident, real, wrong term - that gap is inherent to a
#: general-purpose embedding model on clinical phrasing, and is exactly the
#: motivation the spec itself gives for a future ClinicalBERT upgrade.
DEFAULT_SIMILARITY_THRESHOLD = 0.6

MODEL_NAME = "all-mpnet-base-v2"


@dataclass(frozen=True)
class _Index:
    ids: np.ndarray
    names: np.ndarray
    vectors: np.ndarray  # L2-normalized, (n_terms, dim)


@lru_cache(maxsize=1)
def _load_index() -> _Index:
    """The Step 2A artifact, loaded once per process.

    Raises FileNotFoundError with an actionable message if the index has not
    been built yet - this is a setup step, not something that should fail
    silently into "no candidates ever match".
    """
    if not _INDEX_PATH.exists():
        raise FileNotFoundError(
            f"HPO term index not found at {_INDEX_PATH}. Build it once with: "
            "cd backend && uv run python scripts/build_hpo_index.py"
        )
    data = np.load(_INDEX_PATH, allow_pickle=True)
    return _Index(ids=data["ids"], names=data["names"], vectors=data["vectors"])


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


@lru_cache(maxsize=1)
def _ensure_ontology() -> None:
    """Initialize PyHPO's `Ontology` singleton in this process, once.

    `Ontology.get_hpo_object` reads an internal map that only exists after
    `Ontology()` has been called — skipping this raises a bare `AttributeError`
    from inside PyHPO, not the `RuntimeError` `resolve_hpo` guards against, so
    every caller of `Ontology.get_hpo_object` in this module must go through
    this first.
    """
    Ontology()


def embed_text(text: str) -> np.ndarray:
    """Step 1 — one L2-normalized embedding vector for a free-text description."""
    vector = _model().encode([text], normalize_embeddings=True)[0]
    return np.asarray(vector, dtype=np.float32)


@dataclass
class Candidate:
    hpo_id: str
    name: str
    score: float
    above_threshold: bool


def nearest_candidates(
    text: str, k: int = 5, threshold: float = DEFAULT_SIMILARITY_THRESHOLD
) -> list[Candidate]:
    """Step 2B — the k HPO terms whose index embedding is closest to `text`.

    Vectors are L2-normalized at index build time and here, so cosine
    similarity is a plain dot product. Every one of the k nearest terms is
    returned, each flagged `above_threshold` or not, rather than silently
    dropping the ones below the cutoff - the orchestrator uses that flag to
    decide what reaches Step 3, but a caller inspecting this step directly
    should see the real distribution, not a pre-filtered one.
    """
    index = _load_index()
    query = embed_text(text)
    scores = index.vectors @ query
    top_k = np.argsort(-scores)[:k]
    return [
        Candidate(
            hpo_id=str(index.ids[i]),
            name=str(index.names[i]),
            score=float(scores[i]),
            above_threshold=float(scores[i]) >= threshold,
        )
        for i in top_k
    ]


@dataclass
class ResolvedTerm:
    hpo_id: str
    name: str


@dataclass
class RejectedCandidate:
    hpo_id: str
    reason: str


def resolve_hpo(hpo_id: str) -> ResolvedTerm | RejectedCandidate:
    """Step 3 — the one mandatory checkpoint. A pure existence check, nothing else.

    This is deliberately NOT a comparison between two independently-supplied
    values, and NOT a semantic-relevance judgement - Step 2B already did the
    fuzzy part. This just asks one trusted source (PyHPO's live `Ontology`)
    "does this id exist, and is it current?" - like checking a dictionary key.

    `PyHPO.Ontology.get_hpo_object` also matches by exact term name or synonym
    text, not only by id (e.g. `get_hpo_object("Scoliosis")` resolves). That
    would let a plain-English guess sneak past this checkpoint pretending to be
    a validated id, which is exactly the hallucination risk Step 3 exists to
    close - so a candidate that isn't shaped like `HP:xxxxxxx` is rejected
    outright, before PyHPO is even asked.

    Rejects for one of two reasons, matching the spec exactly:
      - "not a well-formed HPO id"      (wrong shape, before any lookup)
      - "unknown HPO id"                (the id does not exist at all)
      - "obsolete, replaced by HP:..."  (existed once, retired/merged since)
    """
    if not _HPO_ID_RE.match(hpo_id):
        return RejectedCandidate(hpo_id=hpo_id, reason="not a well-formed HPO id")

    _ensure_ontology()
    try:
        term = Ontology.get_hpo_object(hpo_id)
    except (RuntimeError, ValueError, TypeError):
        return RejectedCandidate(hpo_id=hpo_id, reason="unknown HPO id")

    if term.is_obsolete:
        replacement = f", replaced by {term.replaced_by}" if term.replaced_by else ""
        return RejectedCandidate(hpo_id=hpo_id, reason=f"obsolete{replacement}")

    return ResolvedTerm(hpo_id=term.id, name=term.name)


def expand_related_terms(hpo_id: str) -> dict[str, list[dict[str, str]]]:
    """Step 4 — the validated term's parents and children, for display only.

    Not a lookup service and not re-parsed from a file: PyHPO already wired
    every term object to its parents/children when it loaded the ontology, so
    this just reads `.parents` / `.children` off the term `resolve_hpo`
    already confirmed real. Informational only - the caller must not fold
    these into Step 5's gene query (see `phenotype_to_genes`).
    """
    _ensure_ontology()
    term = Ontology.get_hpo_object(hpo_id)
    return {
        "parents": [{"hpo_id": p.id, "name": p.name} for p in term.parents],
        "children": [{"hpo_id": c.id, "name": c.name} for c in term.children],
    }


def genes_for_hpo_terms(hpo_ids: list[str]) -> list[str]:
    """Step 5 — genes implicated by validated HPO term(s), via `hpo_gene_phenotype`.

    Input must already be Step-3-validated ids; this does no validation of its
    own; it is a join, not a checkpoint. Returns a distinct, sorted list of
    `gene_symbol` values, or an empty list if the dataset is not registered
    (e.g. `fetch_hpo.py` has not been run yet) - never a query error surfaced to
    the agent, since "no dataset" and "no genes found" are both empty lists.
    """
    from app.util.registry import registry

    if "hpo_gene_phenotype" not in registry.datasets or not registry.datasets["hpo_gene_phenotype"].available:
        return []
    if not hpo_ids:
        return []

    # "-" is the upstream release's own placeholder for "no gene symbol on this
    # row" (375 of ~332k rows) - a real value in the data, not a parsing bug,
    # but not a gene either, so it is excluded here rather than left for every
    # caller to filter out itself.
    placeholders = ",".join("?" for _ in hpo_ids)
    cursor = registry.cursor().execute(
        f"SELECT DISTINCT gene_symbol FROM hpo_gene_phenotype "
        f"WHERE hpo_id IN ({placeholders}) AND gene_symbol != '-'",
        list(hpo_ids),
    )
    return sorted(row[0] for row in cursor.fetchall())


def phenotype_to_genes(
    text: str, k: int = 5, threshold: float = DEFAULT_SIMILARITY_THRESHOLD
) -> dict[str, Any]:
    """The full pipeline, Steps 1 through 5, as one structured result.

    `validated_terms` is only ever populated from `resolve_hpo` successes -
    nothing reaches it, `related_terms`, or `genes` without passing that
    checkpoint. `related_terms` (Step 4) is informational and explicitly does
    NOT feed `genes` (Step 5), which is built from `validated_terms` alone -
    this mirrors the spec's Step 4/Step 5 decision exactly.
    """
    candidates = nearest_candidates(text, k=k, threshold=threshold)

    validated: list[ResolvedTerm] = []
    rejected: list[RejectedCandidate] = []
    for candidate in candidates:
        if not candidate.above_threshold:
            rejected.append(
                RejectedCandidate(
                    hpo_id=candidate.hpo_id,
                    reason=f"below similarity threshold ({candidate.score:.3f} < {threshold})",
                )
            )
            continue
        outcome = resolve_hpo(candidate.hpo_id)
        (validated if isinstance(outcome, ResolvedTerm) else rejected).append(outcome)

    related = {term.hpo_id: expand_related_terms(term.hpo_id) for term in validated}
    genes = genes_for_hpo_terms([term.hpo_id for term in validated])

    return {
        "query": text,
        "candidates_considered": [
            {"hpo_id": c.hpo_id, "name": c.name, "score": round(c.score, 4), "above_threshold": c.above_threshold}
            for c in candidates
        ],
        "validated_terms": [{"hpo_id": t.hpo_id, "name": t.name} for t in validated],
        "rejected": [{"hpo_id": r.hpo_id, "reason": r.reason} for r in rejected],
        "related_terms": related,
        "genes": genes,
    }
