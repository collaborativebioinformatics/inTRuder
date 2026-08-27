"""Analysis of Evo 2 embeddings: reduction, clustering, and the checks that
keep both honest.

The extraction half (:mod:`evo.embeddings`) runs on a GPU cluster and writes
``.npz`` files; this half runs on a laptop and reads them. Nothing here imports
torch or evo2, so ``uv sync --extra analysis`` is the whole install.

Three shared primitives sit at this level because both steps need them and
neither owns them:

:mod:`analysis.matrix`
    turning a stored run into the ``(n_windows, d)`` float32 matrix an
    estimator can take -- view selection, sanitation, normalisation, and the
    alt-minus-reference difference.
:mod:`analysis.diagnostics`
    the questions to ask *before* believing a picture: what is each axis
    actually tracking, and is the structure just the locus?
:mod:`analysis.plotting`
    one scatter function, so both steps draw the same figure.

The two steps themselves -- :mod:`analysis.dim_reduc` and
:mod:`analysis.clustering` -- do not import each other. They exchange files.
"""
