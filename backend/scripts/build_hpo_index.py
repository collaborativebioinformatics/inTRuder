"""Build the HPO term embedding index — Step 2A of the phenotype-to-loci pipeline.

Unlike `fetch_hpo.py`, this is not a published resource: nobody ships a
precomputed (HPO term -> embedding) index, so it has to be built once, here,
from `PyHPO`'s `Ontology` object (every term's name and synonyms) using the same
`sentence-transformers` model (`all-mpnet-base-v2`) that embeds a query at
request time — Step 2B's cosine similarity is only meaningful if both sides came
from the same model.

    cd backend && uv run python scripts/build_hpo_index.py

Only needs re-running when the HPO version bundled with the installed `pyhpo`
changes, or the embedding model changes — not on every pipeline run, so this is
a script, not something the request path calls.

One embedding per term (name and synonyms concatenated into one string), to
match Step 2A's documented output: one vector per HPO id, not one per synonym.
Vectors are L2-normalized at build time so Step 2B's "cosine similarity" is a
plain dot product against the index, no norm division per query.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from pyhpo import Ontology
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-mpnet-base-v2"

OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "web" / "hpo"
VECTORS_PATH = OUT_DIR / "term_index.npz"
META_PATH = OUT_DIR / "term_index.meta.json"


def _term_text(term) -> str:
    """The text embedded for one term: its canonical name plus every synonym.

    Synonyms matter more than the name for this task — "curved spine" is a
    synonym-shaped query, not a term-name-shaped one — so folding them into the
    same embedded string is what lets casual phrasing land near the right term.
    """
    parts = [term.name, *term.synonym]
    return ". ".join(parts)


def build() -> tuple[list[str], list[str], np.ndarray]:
    Ontology()
    terms = list(Ontology)
    ids = [term.id for term in terms]
    names = [term.name for term in terms]
    texts = [_term_text(term) for term in terms]

    model = SentenceTransformer(MODEL_NAME)
    vectors = model.encode(
        texts,
        batch_size=64,
        show_progress_bar=True,
        normalize_embeddings=True,  # so Step 2B's similarity is a dot product
    )
    return ids, names, np.asarray(vectors, dtype=np.float32)


def main() -> int:
    ids, names, vectors = build()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    np.savez(
        VECTORS_PATH,
        ids=np.array(ids, dtype="U16"),
        names=np.array(names, dtype=object),
        vectors=vectors,
    )
    META_PATH.write_text(
        json.dumps(
            {
                "model": MODEL_NAME,
                "n_terms": len(ids),
                "vector_dim": int(vectors.shape[1]),
                "built_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
    )

    print(f"[hpo-index] {len(ids)} terms, dim {vectors.shape[1]} -> {VECTORS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
