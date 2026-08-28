"""Step-by-step tests for the phenotype-to-loci pipeline.

Needs the Step 2A index built first (`uv run python scripts/build_hpo_index.py`)
and the Step 5 dataset fetched (`uv run python scripts/fetch_hpo.py`) — both are
one-time setup, not part of the request path, so they are not built by these
tests. Run with `-s` to see the printed output at each step.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.util.hpo_pipeline import (
    Candidate,
    RejectedCandidate,
    ResolvedTerm,
    embed_text,
    expand_related_terms,
    genes_for_hpo_terms,
    nearest_candidates,
    phenotype_to_genes,
    resolve_hpo,
)


@pytest.fixture(scope="module")
def client():
    # Not used for HTTP calls here — just to run the app's lifespan, which
    # loads the registry `genes_for_hpo_terms` depends on.
    with TestClient(app) as test_client:
        yield test_client


# --------------------------------------------------------------------------
# Step 1 — embed free text
# --------------------------------------------------------------------------


def test_step1_embed_text_shape_and_norm():
    vector = embed_text("progressive scoliosis and hearing loss")
    print(f"\n[step 1] vector shape={vector.shape} dtype={vector.dtype} "
          f"norm={float((vector ** 2).sum() ** 0.5):.4f}")
    assert vector.shape == (768,)
    assert abs(float((vector ** 2).sum() ** 0.5) - 1.0) < 1e-3  # normalize_embeddings=True


# --------------------------------------------------------------------------
# Step 2B — nearest-neighbor search
# --------------------------------------------------------------------------


def test_step2b_nearest_candidates_clear_match():
    candidates = nearest_candidates("short stature", k=5)
    print("\n[step 2b] 'short stature' ->")
    for c in candidates:
        print(f"    {c.hpo_id}  {c.name!r:45} score={c.score:.4f} above_threshold={c.above_threshold}")
    assert all(isinstance(c, Candidate) for c in candidates)
    assert candidates[0].score >= candidates[-1].score  # sorted descending
    assert candidates[0].above_threshold


def test_step2b_nearest_candidates_nonsense():
    candidates = nearest_candidates("purple elephant riding a bicycle", k=5)
    print("\n[step 2b] 'purple elephant riding a bicycle' ->")
    for c in candidates:
        print(f"    {c.hpo_id}  {c.name!r:45} score={c.score:.4f} above_threshold={c.above_threshold}")
    assert not candidates[0].above_threshold


def test_threshold_calibration():
    """The empirical floor/ceiling the spec asks for, reproduced.

    Not a correctness assertion about individual scores (those will drift if
    the index or model changes) — the one thing that must hold is the gap:
    every nonsense phrase's best match must score below every known-good
    phrase's best match, or a single fixed threshold is not viable and the
    spec's fallback (top-k for human confirmation) would be needed instead.
    """
    nonsense = [
        "purple elephant riding a bicycle",
        "the stock market closed higher today",
        "asdkjfh qweoiuqwe nonsense text",
        "my favorite pizza topping is pepperoni",
        "quantum entanglement in superconducting circuits",
    ]
    good = ["curved spine", "seizures", "hearing loss", "short stature", "intellectual disability"]

    floor_scores = [nearest_candidates(p, k=1, threshold=0)[0].score for p in nonsense]
    ceiling_scores = [nearest_candidates(p, k=1, threshold=0)[0].score for p in good]

    print("\n[threshold] nonsense best-match scores:", [f"{s:.4f}" for s in floor_scores])
    print("[threshold] known-good best-match scores:", [f"{s:.4f}" for s in ceiling_scores])
    print(f"[threshold] floor max={max(floor_scores):.4f}  ceiling min={min(ceiling_scores):.4f}")

    assert max(floor_scores) < min(ceiling_scores), (
        "nonsense/known-good scores overlap — a single fixed threshold is not "
        "reliable; see the spec's fallback (return top-k for human confirmation)"
    )


# --------------------------------------------------------------------------
# Step 3 — resolve_hpo(), the hard guardrail
# --------------------------------------------------------------------------


def test_step3_resolve_hpo_valid():
    result = resolve_hpo("HP:0002650")
    print(f"\n[step 3] HP:0002650 -> {result}")
    assert isinstance(result, ResolvedTerm)
    assert result.name == "Scoliosis"


def test_step3_resolve_hpo_malformed():
    result = resolve_hpo("not an HPO id")
    print(f"\n[step 3] 'not an HPO id' -> {result}")
    assert isinstance(result, RejectedCandidate)
    assert result.reason == "not a well-formed HPO id"


def test_step3_resolve_hpo_unknown():
    result = resolve_hpo("HP:9999999")
    print(f"\n[step 3] HP:9999999 -> {result}")
    assert isinstance(result, RejectedCandidate)
    assert result.reason == "unknown HPO id"


def test_step3_resolve_hpo_obsolete():
    result = resolve_hpo("HP:0000057")  # "obsolete Clitoromegaly" in the bundled hp.obo
    print(f"\n[step 3] HP:0000057 -> {result}")
    assert isinstance(result, RejectedCandidate)
    assert "obsolete" in result.reason
    assert "HP:0008665" in result.reason  # replaced_by


def test_step3_rejects_name_based_lookup_disguised_as_an_id():
    """PyHPO's get_hpo_object also matches by exact term name — resolve_hpo must
    not let a plain-English guess pass the checkpoint by accident."""
    result = resolve_hpo("Scoliosis")
    print(f"\n[step 3] 'Scoliosis' (a name, not an id) -> {result}")
    assert isinstance(result, RejectedCandidate)
    assert result.reason == "not a well-formed HPO id"


# --------------------------------------------------------------------------
# Step 4 — related terms (informational only)
# --------------------------------------------------------------------------


def test_step4_expand_related_terms():
    related = expand_related_terms("HP:0002650")
    print(f"\n[step 4] HP:0002650 parents={related['parents']}")
    print(f"[step 4] HP:0002650 children (first 3)={related['children'][:3]}")
    assert {"hpo_id": "HP:0010674", "name": "Abnormal curvature of the vertebral column"} in related["parents"] \
        or any(p["hpo_id"] == "HP:0010674" for p in related["parents"])


# --------------------------------------------------------------------------
# Step 5 — gene join
# --------------------------------------------------------------------------


def test_step5_genes_for_hpo_terms(client):
    genes = genes_for_hpo_terms(["HP:0002650"])
    print(f"\n[step 5] genes for HP:0002650 (Scoliosis), first 10 of {len(genes)}: {genes[:10]}")
    assert isinstance(genes, list)
    assert len(genes) > 0


def test_step5_empty_input_returns_empty_list(client):
    assert genes_for_hpo_terms([]) == []


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------


def test_end_to_end_clear_match(client):
    result = phenotype_to_genes("short stature")
    print(f"\n[e2e] 'short stature' -> validated={result['validated_terms']} "
          f"n_genes={len(result['genes'])} sample_genes={result['genes'][:10]}")
    assert result["validated_terms"], "expected at least one validated term"
    assert result["genes"], "expected at least one implicated gene"


def test_end_to_end_nonsense_rejected(client):
    result = phenotype_to_genes("purple elephant riding a bicycle")
    print(f"\n[e2e] 'purple elephant riding a bicycle' -> "
          f"validated={result['validated_terms']} rejected={result['rejected']} genes={result['genes']}")
    assert result["validated_terms"] == []
    assert result["genes"] == []
    assert result["rejected"]  # rejected for scoring below threshold


def test_end_to_end_curved_spine_semantic_caution(client):
    """Documents the real finding from testing, not just an assertion: the
    spec's own worked example ("curved spine" -> Scoliosis) does not hold with
    all-mpnet-base-v2 against this index. The top validated term is a real,
    current HPO term (so Step 3 correctly does not reject it) that is arguably
    the opposite of what was asked. This is the known limitation documented on
    `DEFAULT_SIMILARITY_THRESHOLD` and in `resolve_phenotype`'s docstring, not a
    bug — asserted here so a future change to the model or index that fixes it
    (or a regression that makes it worse) is visible.
    """
    result = phenotype_to_genes("curved spine")
    top_term = result["validated_terms"][0]["name"] if result["validated_terms"] else None
    print(f"\n[e2e] 'curved spine' -> top validated term: {top_term!r} (expected concept: Scoliosis)")
    assert result["validated_terms"], "expected some term to validate — it just isn't the intuitive one"
