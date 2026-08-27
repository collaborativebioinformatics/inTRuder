"""Clustering and outlier scoring over Evo 2 embedding views.

Two different questions get called "clustering" here and they want different
tools:

*Are there groups?* k-means, agglomerative and HDBSCAN, scored by internal
indices and -- more usefully -- by agreement with the covariates we already
know. A clustering that recovers ``locus`` at ARI 0.98 has rediscovered the
flanks; the interesting result is a partition that agrees with *none* of the
known labels and still holds up.

*Is this one unusual?* :func:`~analysis.clustering.cluster.novelty_scores`
measures each insertion against the reference-allele background at the same
loci. That is closer to what the project is actually asking -- a novel TR is not
unusual as sequence, it is unusual in being placed here -- and it needs no
cluster boundaries at all.

The CLI is :mod:`analysis.clustering.cli` (``analysis-cluster``).
"""

from analysis.clustering.cluster import (
    METHODS,
    Clustering,
    agreement,
    cluster,
    novelty_scores,
    sweep_k,
)

__all__ = [
    "METHODS", "Clustering", "agreement", "cluster", "novelty_scores", "sweep_k",
]
