"""Evo 2 based annotation of novel tandem repeats.

Two halves, deliberately kept apart because they run in different places:

``evo.embeddings``
    builds sequence windows and runs Evo 2 over them. Needs Linux, CUDA and the
    ``evo2`` package, so in practice it runs on a cluster. Writes ``.npz``.
Downstream analysis of those vectors -- clustering, reduction, outlier scoring
-- is deliberately not here; it is owned separately and reads the ``.npz``.

The split is not tidiness. ``evo2`` requires Python <3.13 while this project
pins 3.13, so the two halves cannot share an interpreter -- and the analysis
half is the one you iterate on, so it is the half that should not need a GPU
queue.
"""
